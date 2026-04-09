"""Build session knowledge markdown (API / pipeline dumps), chunk to ≤10MB, upload to vector store."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from src.chat.session_vector_store import (
    detach_and_delete_openai_knowledge_files,
    ensure_session_vector_store_in_db,
    session_knowledge_dir,
)
from src.db.bot2_synonyms import fetch_latest_bot2_display_lines
from src.db.chat_pipeline import (
    STEP_BOT1_TOPICS_CONNOTATIONS,
    fetch_latest_bot1_analysis_dict,
    get_chat_session_openai_vector_store_id,
)
from src.db.step6_report import (
    delete_step6_knowledge_files_for_session,
    insert_step6_knowledge_file,
    list_step6_knowledge_files,
    max_step6_knowledge_chunk_index,
)
from src.openai_platform.resources import OpenAIAdminError, attach_file_to_vector_store, upload_file_to_openai

MAX_KNOWLEDGE_CHUNK_BYTES = 10 * 1024 * 1024

_VERSE_REF_RE = re.compile(r"\b(\d{1,3})\s*:\s*(\d{1,3})\b")


def extract_surah_ayah_refs(text: str) -> set[tuple[int, int]]:
    """Collect surah:ayah patterns (ASCII digits) from text."""
    if not text:
        return set()
    return {(int(a), int(b)) for a, b in _VERSE_REF_RE.findall(text)}


class _ChunkWriter:
    """Write UTF-8 markdown rotating files when size would exceed max_bytes."""

    def __init__(self, out_dir: Path, *, max_bytes: int = MAX_KNOWLEDGE_CHUNK_BYTES) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self._dir = out_dir
        self._max = max_bytes
        self._part = 0
        self._path: Path | None = None
        self._fh = None
        self._size = 0
        self.paths: list[Path] = []

    def _open_next(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
        self._path = self._dir / f"session_knowledge_part{self._part:02d}.md"
        self._part += 1
        self._fh = self._path.open("w", encoding="utf-8", newline="\n")
        self._size = 0
        self.paths.append(self._path)

    def append(self, s: str) -> None:
        """Append a string that is at most max_bytes UTF-8 (callers must split larger blobs)."""
        raw = s.encode("utf-8")
        if len(raw) > self._max:
            raise ValueError("append chunk exceeds max_bytes; split before calling")
        if self._fh is None:
            self._open_next()
        assert self._fh is not None
        if self._size + len(raw) > self._max and self._size > 0:
            self._open_next()
            assert self._fh is not None
        self._fh.write(s)
        self._size += len(raw)

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def _append_text_chunked(writer: _ChunkWriter, text: str) -> None:
    """Append text, splitting by lines (or byte slices) so no write exceeds max_bytes."""
    if not text:
        return
    if len(text.encode("utf-8")) <= writer._max:
        writer.append(text)
        return
    lines = text.splitlines(keepends=True)
    buf: list[str] = []
    buf_bytes = 0
    for line in lines:
        lb = line.encode("utf-8")
        if len(lb) > writer._max:
            if buf:
                writer.append("".join(buf))
                buf = []
                buf_bytes = 0
            for i in range(0, len(lb), writer._max):
                writer.append(lb[i : i + writer._max].decode("utf-8", errors="replace"))
            continue
        if buf_bytes + len(lb) > writer._max and buf:
            writer.append("".join(buf))
            buf = []
            buf_bytes = 0
        buf.append(line)
        buf_bytes += len(lb)
    if buf:
        writer.append("".join(buf))


def _section(title: str, body: str) -> str:
    return f"\n## {title}\n\n{body.strip()}\n\n"


def iter_knowledge_document_pieces(conn: sqlite3.Connection, chat_session_id: str) -> Iterator[str]:
    yield "# Session knowledge export\n\n"
    yield f"**Session ID:** `{chat_session_id}`\n\n"

    # Question refiner
    qrows = conn.execute(
        """
        SELECT role, bot_name, content, model, response_id,
               prompt_tokens, completion_tokens, total_tokens, created_at
        FROM question_refiner_messages
        WHERE chat_session_id = ?
        ORDER BY id ASC
        """,
        (chat_session_id,),
    ).fetchall()
    parts_q: list[str] = []
    for r in qrows:
        parts_q.append(
            f"### {r['role']} ({r['bot_name']}) — {r['created_at']}\n"
            f"- model: {r['model']!r}, response_id: {r['response_id']!r}\n"
            f"- tokens: {r['prompt_tokens']}/{r['completion_tokens']}/{r['total_tokens']}\n\n"
            f"{r['content']}\n\n---\n\n"
        )
    yield _section("Question refiner messages", "".join(parts_q) if parts_q else "_(none)_")

    # Bot 1
    bot1 = fetch_latest_bot1_analysis_dict(conn, chat_session_id)
    meta1 = conn.execute(
        """
        SELECT model, openai_response_id, prompt_tokens, completion_tokens, total_tokens, created_at
        FROM pipeline_step_runs
        WHERE chat_session_id = ? AND step_key = ?
        ORDER BY id DESC LIMIT 1
        """,
        (chat_session_id, STEP_BOT1_TOPICS_CONNOTATIONS),
    ).fetchone()
    bot1_blob = ""
    if meta1:
        bot1_blob += (
            f"- run model: {meta1['model']!r}, response_id: {meta1['openai_response_id']!r}\n"
            f"- tokens: {meta1['prompt_tokens']}/{meta1['completion_tokens']}/{meta1['total_tokens']}\n"
            f"- created_at: {meta1['created_at']}\n\n"
        )
    if bot1:
        bot1_blob += "```json\n" + json.dumps(bot1, ensure_ascii=False, indent=2) + "\n```\n"
    else:
        bot1_blob += "_(no Bot 1 analysis in DB)_"
    yield _section("Bot 1 — topics / connotations", bot1_blob)

    # Bot 2
    lines2 = fetch_latest_bot2_display_lines(conn, chat_session_id)
    yield _section(
        "Bot 2 — synonyms (latest per connotation)",
        "\n".join(lines2) if lines2 else "_(none)_",
    )

    # Find verses
    fv = conn.execute(
        """
        SELECT id, source_kind, query_text, surah_no, ayah_no, bot2_synonym_term_id, created_at
        FROM find_verse_matches
        WHERE chat_session_id = ?
        ORDER BY id ASC
        """,
        (chat_session_id,),
    ).fetchall()
    fv_lines: list[str] = []
    for r in fv:
        fv_lines.append(
            f"- id={r['id']} {r['surah_no']}:{r['ayah_no']} via {r['source_kind']} "
            f"query={r['query_text']!r} syn_term={r['bot2_synonym_term_id']} ({r['created_at']})\n"
        )
    vt = conn.execute(
        """
        SELECT surah_no, ayah_no, verse_text FROM quran_verses
        WHERE (surah_no, ayah_no) IN (
            SELECT DISTINCT surah_no, ayah_no FROM find_verse_matches
            WHERE chat_session_id = ?
        )
        """,
        (chat_session_id,),
    ).fetchall()
    for r in vt:
        fv_lines.append(
            f"\n**Verse {r['surah_no']}:{r['ayah_no']}**\n\n{r['verse_text']}\n\n"
        )
    yield _section("Step 3 — Find verses (matches + verse text)", "".join(fv_lines) if fv_lines else "_(none)_")

    # Step 5 synthesis results
    s5 = conn.execute(
        """
        SELECT id, surah_no, ayah_no, verse_text, user_payload_json, raw_response_text,
               response_json, exegesis, symbolic_reasoning, possibility_score,
               prompt_tokens, completion_tokens, total_tokens, cost_usd, provider, model, created_at
        FROM step5_synthesis_results
        WHERE chat_session_id = ?
        ORDER BY id ASC
        """,
        (chat_session_id,),
    ).fetchall()
    if not s5:
        yield _section("Step 5 — synthesis results", "_(none)_")
    else:
        yield "\n## Step 5 — synthesis results\n\n"
        for r in s5:
            block = (
                f"### Result id={r['id']} — {r['surah_no']}:{r['ayah_no']}\n\n"
                f"- provider/model: {r['provider']} / {r['model']}\n"
                f"- tokens: {r['prompt_tokens']}/{r['completion_tokens']}/{r['total_tokens']}, "
                f"cost_usd: {r['cost_usd']}, score: {r['possibility_score']}\n"
                f"- created_at: {r['created_at']}\n\n"
                f"**Verse text:** {r['verse_text']}\n\n"
                f"**User payload (JSON):**\n```json\n{r['user_payload_json']}\n```\n\n"
            )
            if r["raw_response_text"]:
                block += f"**Raw response:**\n\n{r['raw_response_text']}\n\n"
            if r["response_json"]:
                block += f"**response_json:**\n```json\n{r['response_json']}\n```\n\n"
            if r["exegesis"]:
                block += f"**exegesis:**\n{r['exegesis']}\n\n"
            if r["symbolic_reasoning"]:
                block += f"**symbolic_reasoning:**\n{r['symbolic_reasoning']}\n\n"
            yield block


def build_knowledge_files(
    conn: sqlite3.Connection, chat_session_id: str, out_dir: Path | None = None
) -> list[Path]:
    d = out_dir or session_knowledge_dir(chat_session_id)
    writer = _ChunkWriter(d)
    try:
        for piece in iter_knowledge_document_pieces(conn, chat_session_id):
            _append_text_chunked(writer, piece)
    finally:
        writer.close()
    return writer.paths


def knowledge_markdown_for_appendix(conn: sqlite3.Connection, chat_session_id: str) -> str:
    return "".join(iter_knowledge_document_pieces(conn, chat_session_id))


def clear_session_step6_knowledge(
    conn: sqlite3.Connection,
    chat_session_id: str,
    *,
    delete_openai_file_objects: bool = True,
    delete_local_files: bool = True,
) -> int:
    """
    Detach all Step 6 knowledge files from this session's vector store and clear DB rows.
    Returns count of removed DB rows.
    """
    vid = get_chat_session_openai_vector_store_id(conn, chat_session_id)
    rows = list_step6_knowledge_files(conn, chat_session_id)
    n = len(rows)
    if vid and rows:
        detach_and_delete_openai_knowledge_files(
            vid,
            [r.openai_file_id for r in rows],
            delete_remote_file_objects=delete_openai_file_objects,
        )
    delete_step6_knowledge_files_for_session(conn, chat_session_id, commit=False)
    conn.commit()
    if delete_local_files:
        for r in rows:
            try:
                Path(r.local_path).unlink(missing_ok=True)
            except OSError:
                pass
    return n


def replace_knowledge_on_vector_store(
    conn: sqlite3.Connection,
    chat_session_id: str,
    session_title: str | None,
    *,
    replace_remote: bool = True,
    delete_openai_file_objects: bool = True,
    clear_local_knowledge_dir_first: bool = False,
) -> tuple[str, list[Path]]:
    """
    Ensure vector store; optionally replace prior remote+DB state; write chunks; upload & attach.

    - replace_remote: if True (default), remove previous vector attachments and DB file rows
      before uploading a fresh export. If False, **append** a new batch (new subfolder, new indices).
    - delete_openai_file_objects: detach from vector store and delete Files API objects (when replacing).
    - clear_local_knowledge_dir_first: when replacing, delete the entire local ``knowledge`` directory
      before writing (only if replace_remote).

    Always ensures a per-session OpenAI vector store exists and is saved on ``chat_sessions``
    (sessions from before Step 6 may not have one until the first successful Load).
    """
    vid = ensure_session_vector_store_in_db(conn, chat_session_id, session_title)
    if not vid:
        raise OpenAIAdminError("Could not create or load vector store for session.")

    base_dir = session_knowledge_dir(chat_session_id)

    if replace_remote:
        prev = list_step6_knowledge_files(conn, chat_session_id)
        if prev:
            detach_and_delete_openai_knowledge_files(
                vid,
                [r.openai_file_id for r in prev],
                delete_remote_file_objects=delete_openai_file_objects,
            )
        delete_step6_knowledge_files_for_session(conn, chat_session_id, commit=False)
        conn.commit()

        if clear_local_knowledge_dir_first and base_dir.is_dir():
            shutil.rmtree(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        paths = build_knowledge_files(conn, chat_session_id, out_dir=base_dir)
        start_idx = 0
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = base_dir / f"batch_{stamp}"
        paths = build_knowledge_files(conn, chat_session_id, out_dir=out_dir)
        start_idx = max_step6_knowledge_chunk_index(conn, chat_session_id) + 1

    for off, p in enumerate(paths):
        up = upload_file_to_openai(p, purpose="assistants")
        fid = str(up["id"])
        attach_file_to_vector_store(vid, fid)
        insert_step6_knowledge_file(
            conn,
            chat_session_id=chat_session_id,
            openai_file_id=fid,
            chunk_index=start_idx + off,
            local_path=str(p.resolve()),
            commit=True,
        )
    return vid, paths
