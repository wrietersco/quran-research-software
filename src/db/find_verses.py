"""Step 3 — Find Verses: exact token-sequence matches in quran_tokens for connotations / Bot 2 synonyms."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.db.bot2_synonyms import (
    ConnotationWorkItem,
    latest_bot1_pipeline_run_id,
    list_connotations_for_bot1_run,
)
from src.db.chat_pipeline import refined_question_id_for_session
from src.db.find_match_words import populate_find_match_word_rows_for_session
from src.config import QURAN_ROOT_JSON
from src.normalize.arabic import normalize_arabic


def quran_token_row_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM quran_tokens").fetchone()
    return int(row["c"]) if row else 0


def _normalize_for_match(s: str) -> str:
    """
    Align Bot / synonym text with stored token_plain for comparison.

    Importer stores normalize_arabic(uthmani) with unify_ta_marbuta=False; models often
    write ه where the corpus has ة. Using unify_ta_marbuta=True on both sides fixes many
    otherwise identical strings.
    """
    return normalize_arabic((s or "").strip(), unify_ta_marbuta=True)


_MIN_FULL_QURAN_TOKEN_ROWS = 1000


def _quran_json_path() -> Path:
    return QURAN_ROOT_JSON


@lru_cache(maxsize=1)
def _load_ayah_token_lists_from_quran_json(
    path_str: str, mtime_ns: int
) -> dict[tuple[int, int], list[str]]:
    # mtime_ns is included in the cache key so edits to quran.json invalidate cache.
    _ = mtime_ns
    p = Path(path_str)
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[tuple[int, int], list[str]] = {}

    if isinstance(data, dict):
        groups = data.values()
    elif isinstance(data, list):
        groups = [data]
    else:
        return out

    for group in groups:
        if not isinstance(group, list):
            continue
        for row in group:
            if not isinstance(row, dict):
                continue
            surah_raw = row.get("chapter", row.get("surah", row.get("surah_no")))
            ayah_raw = row.get("verse", row.get("ayah", row.get("ayah_no")))
            text_raw = row.get("text", "")
            if surah_raw is None or ayah_raw is None:
                continue
            try:
                surah_no = int(surah_raw)
                ayah_no = int(ayah_raw)
            except (TypeError, ValueError):
                continue
            text = str(text_raw or "").strip()
            norm = _normalize_for_match(text)
            parts = [p for p in norm.split() if p]
            if parts:
                out[(surah_no, ayah_no)] = parts
    return out


@lru_cache(maxsize=1)
def _load_ayah_texts_from_quran_json(path_str: str, mtime_ns: int) -> dict[tuple[int, int], str]:
    _ = mtime_ns
    p = Path(path_str)
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[tuple[int, int], str] = {}

    if isinstance(data, dict):
        groups = data.values()
    elif isinstance(data, list):
        groups = [data]
    else:
        return out

    for group in groups:
        if not isinstance(group, list):
            continue
        for row in group:
            if not isinstance(row, dict):
                continue
            surah_raw = row.get("chapter", row.get("surah", row.get("surah_no")))
            ayah_raw = row.get("verse", row.get("ayah", row.get("ayah_no")))
            if surah_raw is None or ayah_raw is None:
                continue
            try:
                surah_no = int(surah_raw)
                ayah_no = int(ayah_raw)
            except (TypeError, ValueError):
                continue
            text = str(row.get("text", "") or "").strip()
            if text:
                out[(surah_no, ayah_no)] = text
    return out


def load_search_ayah_token_lists(
    conn: sqlite3.Connection,
) -> tuple[dict[tuple[int, int], list[str]], str, int]:
    """
    Choose the best available corpus for verse matching.
    Returns (ayah_map, source_label, token_count).
    """
    n_tokens = quran_token_row_count(conn)
    if n_tokens >= _MIN_FULL_QURAN_TOKEN_ROWS:
        ayah_map = load_ayah_token_lists(conn)
        return ayah_map, "quran_tokens", n_tokens

    p = _quran_json_path()
    if p.is_file():
        st = p.stat()
        ayah_map = _load_ayah_token_lists_from_quran_json(str(p), st.st_mtime_ns)
        if ayah_map:
            token_count = sum(len(v) for v in ayah_map.values())
            return ayah_map, "quran.json", token_count

    if n_tokens > 0:
        ayah_map = load_ayah_token_lists(conn)
        return ayah_map, "quran_tokens_partial", n_tokens
    return {}, "none", 0


def fetch_ayah_texts(
    conn: sqlite3.Connection, refs: list[tuple[int, int]]
) -> dict[tuple[int, int], str]:
    """Best-effort ayah Arabic text for display, keyed by (surah_no, ayah_no)."""
    want = {(int(su), int(ay)) for su, ay in refs}
    if not want:
        return {}

    picked: dict[tuple[int, int], str] = {}
    clauses = " OR ".join(["(surah_no = ? AND ayah_no = ?)" for _ in want])
    params: list[int] = []
    for su, ay in want:
        params.extend([su, ay])
    try:
        vrows = conn.execute(
            f"SELECT surah_no, ayah_no, verse_text FROM quran_verses WHERE {clauses}",
            params,
        ).fetchall()
    except sqlite3.Error:
        vrows = []
    for r in vrows:
        k = (int(r["surah_no"]), int(r["ayah_no"]))
        picked[k] = str(r["verse_text"] or "")

    missing = want - picked.keys()
    if missing:
        p = _quran_json_path()
        if p.is_file():
            st = p.stat()
            all_texts = _load_ayah_texts_from_quran_json(str(p), st.st_mtime_ns)
            for k in list(missing):
                if k in all_texts:
                    picked[k] = all_texts[k]
            missing = want - picked.keys()

    if missing:
        clauses2 = " OR ".join(["(surah_no = ? AND ayah_no = ?)" for _ in missing])
        params2: list[int] = []
        for su, ay in missing:
            params2.extend([su, ay])
        rows = conn.execute(
            f"""
            SELECT surah_no, ayah_no, word_no, token_uthmani
            FROM quran_tokens
            WHERE {clauses2}
            ORDER BY surah_no ASC, ayah_no ASC, word_no ASC
            """,
            params2,
        ).fetchall()
        grouped: dict[tuple[int, int], list[str]] = defaultdict(list)
        for r in rows:
            key = (int(r["surah_no"]), int(r["ayah_no"]))
            t = str(r["token_uthmani"] or "").strip()
            if t:
                grouped[key].append(t)
        for k, toks in grouped.items():
            picked[k] = " ".join(toks)

    return picked


def load_ayah_token_lists(conn: sqlite3.Connection) -> dict[tuple[int, int], list[str]]:
    """Map (surah_no, ayah_no) -> ordered match-normalized tokens (see _normalize_for_match)."""
    cur = conn.execute(
        """
        SELECT surah_no, ayah_no, word_no, token_plain
        FROM quran_tokens
        ORDER BY surah_no, ayah_no, word_no
        """
    )
    out: dict[tuple[int, int], list[str]] = {}
    for row in cur.fetchall():
        key = (int(row["surah_no"]), int(row["ayah_no"]))
        plain = str(row["token_plain"] or "")
        out.setdefault(key, []).append(_normalize_for_match(plain))
    return out


def normalized_token_parts(text: str) -> list[str] | None:
    """Normalize for verse matching; split on whitespace. None if nothing to search."""
    norm = _normalize_for_match((text or "").strip())
    if not norm:
        return None
    parts = [p for p in norm.split() if p]
    return parts if parts else None


def find_matching_ayahs(
    ayah_tokens: dict[tuple[int, int], list[str]],
    parts: list[str],
) -> list[tuple[int, int]]:
    """Ayat where a contiguous subsequence of match-normalized tokens equals parts (one hit per ayah max)."""
    if not parts:
        return []
    n = len(parts)
    hits: list[tuple[int, int]] = []
    for (su, ay), toks in ayah_tokens.items():
        if len(toks) < n:
            continue
        for start in range(len(toks) - n + 1):
            if toks[start : start + n] == parts:
                hits.append((su, ay))
                break
    return hits


def latest_synonym_terms_for_connotation(
    conn: sqlite3.Connection, bot1_connotation_id: int
) -> list[tuple[int, str]]:
    """(bot2_synonym_terms.id, synonym_text) from the latest bot2_synonym_runs row for this connotation."""
    rows = conn.execute(
        """
        SELECT st.id AS tid, st.synonym_text
        FROM bot2_synonym_terms st
        JOIN bot2_synonym_runs sr ON sr.id = st.bot2_synonym_run_id
        WHERE sr.bot1_connotation_id = ?
          AND sr.id = (
              SELECT MAX(sr2.id)
              FROM bot2_synonym_runs sr2
              WHERE sr2.bot1_connotation_id = ?
          )
        ORDER BY st.sort_order ASC, st.id ASC
        """,
        (bot1_connotation_id, bot1_connotation_id),
    ).fetchall()
    out: list[tuple[int, str]] = []
    for r in rows:
        tid = int(r["tid"])
        stext = str(r["synonym_text"] or "").strip()
        if stext:
            out.append((tid, stext))
    return out


@dataclass(frozen=True)
class FindVersesStats:
    """Stats from run_find_verses_for_session; includes queries with zero ayah matches."""

    rows_inserted: int
    connotations_processed: int
    queries_run: int
    skipped_empty_queries: int
    quran_token_count: int
    ayah_count: int
    corpus_source: str
    # (bot1_connotation_id, text) — had searchable tokens but no ayah match
    not_found_connotations: tuple[tuple[int, str], ...] = ()
    # (bot1_connotation_id, bot2_synonym_term_id, text) — had searchable tokens but no ayah match
    not_found_synonyms: tuple[tuple[int, int, str], ...] = ()
    # Rows inserted into find_match_word_rows (per quran_tokens word per saved hit)
    match_word_rows_inserted: int = 0


def run_find_verses_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> FindVersesStats:
    """
    Delete existing matches for the session, then scan latest Bot 1 connotations (+ latest Bot 2 synonyms each).
    Requires session_refined_questions row and Bot 1 pipeline data.
    """
    rq_id = refined_question_id_for_session(conn, chat_session_id)
    if rq_id is None:
        raise ValueError("No finalized refined question for this session.")

    b1_run = latest_bot1_pipeline_run_id(conn, chat_session_id)
    if b1_run is None:
        raise ValueError("No Bot 1 pipeline run for this session.")

    items: list[ConnotationWorkItem] = list_connotations_for_bot1_run(conn, b1_run)
    if not items:
        raise ValueError("No connotations in the latest Bot 1 run.")

    ayah_map, corpus_source, corpus_tokens = load_search_ayah_token_lists(conn)
    if not ayah_map:
        raise ValueError(
            "No searchable Quran corpus found. "
            "Import a word-by-word Quran JSON into quran_tokens (recommended), or keep "
            "a full quran.json at project root for fallback search. "
            "Example import: "
            "`python scripts/import_quran.py <path-to-words.json>` "
            "(see README.md)."
        )

    conn.execute(
        "DELETE FROM find_verse_matches WHERE chat_session_id = ?",
        (chat_session_id,),
    )
    inserted = 0
    queries = 0
    skipped = 0
    not_found_connotations: list[tuple[int, str]] = []
    not_found_synonyms: list[tuple[int, int, str]] = []

    for item in items:
        cid = item.bot1_connotation_id

        parts = normalized_token_parts(item.connotation_text)
        if parts:
            queries += 1
            con_hits = find_matching_ayahs(ayah_map, parts)
            if not con_hits:
                not_found_connotations.append((cid, item.connotation_text.strip()))
            for su, ay in con_hits:
                conn.execute(
                    """
                    INSERT INTO find_verse_matches (
                        chat_session_id, refined_question_id, bot1_connotation_id,
                        source_kind, bot2_synonym_term_id, query_text,
                        surah_no, ayah_no
                    )
                    VALUES (?, ?, ?, 'connotation', NULL, ?, ?, ?)
                    """,
                    (
                        chat_session_id,
                        rq_id,
                        cid,
                        item.connotation_text.strip(),
                        su,
                        ay,
                    ),
                )
                inserted += 1
        else:
            skipped += 1

        for term_id, syn_text in latest_synonym_terms_for_connotation(conn, cid):
            sparts = normalized_token_parts(syn_text)
            if not sparts:
                skipped += 1
                continue
            queries += 1
            syn_hits = find_matching_ayahs(ayah_map, sparts)
            if not syn_hits:
                not_found_synonyms.append((cid, term_id, syn_text.strip()))
            for su, ay in syn_hits:
                conn.execute(
                    """
                    INSERT INTO find_verse_matches (
                        chat_session_id, refined_question_id, bot1_connotation_id,
                        source_kind, bot2_synonym_term_id, query_text,
                        surah_no, ayah_no
                    )
                    VALUES (?, ?, ?, 'synonym', ?, ?, ?, ?)
                    """,
                    (
                        chat_session_id,
                        rq_id,
                        cid,
                        term_id,
                        syn_text.strip(),
                        su,
                        ay,
                    ),
                )
                inserted += 1

    n_word_rows = populate_find_match_word_rows_for_session(conn, chat_session_id)
    conn.commit()
    return FindVersesStats(
        rows_inserted=inserted,
        connotations_processed=len(items),
        queries_run=queries,
        skipped_empty_queries=skipped,
        quran_token_count=corpus_tokens,
        ayah_count=len(ayah_map),
        corpus_source=corpus_source,
        not_found_connotations=tuple(not_found_connotations),
        not_found_synonyms=tuple(not_found_synonyms),
        match_word_rows_inserted=n_word_rows,
    )


def search_arabic_text_in_quran(
    conn: sqlite3.Connection, arabic_text: str
) -> tuple[list[tuple[int, int]], str | None]:
    """
    Preview-only search: same token-sequence rule as pipeline Find Verses.
    Returns (hits, error_message). error_message set when nothing to search or corpus empty.
    """
    parts = normalized_token_parts(arabic_text)
    if not parts:
        return [], "Empty or unsearchable text after normalization."
    ayah_map, corpus_source, _corpus_tokens = load_search_ayah_token_lists(conn)
    if not ayah_map:
        return [], (
            "No searchable Quran corpus found. "
            "Import word-level Quran into quran_tokens, or keep full quran.json at project root."
        )
    hits = find_matching_ayahs(ayah_map, parts)
    if not hits and corpus_source == "quran_tokens_partial":
        return [], (
            "No match in current partial quran_tokens corpus. "
            "Your DB appears to contain only a small sample; import full Quran words JSON "
            "or keep full quran.json at project root."
        )
    return hits, None


def save_adhoc_verse_matches(
    conn: sqlite3.Connection,
    chat_session_id: str,
    query_text: str,
    hits: list[tuple[int, int]],
) -> int:
    """
    Replace saved rows for this session + exact query_text, then insert current hits.
    Caller should upsert chat_sessions first. Commits.
    """
    q = (query_text or "").strip()
    conn.execute(
        "DELETE FROM find_verse_adhoc_matches WHERE chat_session_id = ? AND query_text = ?",
        (chat_session_id, q),
    )
    for su, ay in hits:
        conn.execute(
            """
            INSERT INTO find_verse_adhoc_matches (chat_session_id, query_text, surah_no, ayah_no)
            VALUES (?, ?, ?, ?)
            """,
            (chat_session_id, q, int(su), int(ay)),
        )
    conn.commit()
    return len(hits)


def fetch_adhoc_verse_matches_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, query_text, surah_no, ayah_no, created_at
        FROM find_verse_adhoc_matches
        WHERE chat_session_id = ?
        ORDER BY query_text ASC, surah_no ASC, ayah_no ASC, id ASC
        """,
        (chat_session_id,),
    ).fetchall()


def group_adhoc_rows_by_query(rows: list[sqlite3.Row]) -> dict[str, list[tuple[int, int]]]:
    by_q: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for r in rows:
        by_q[str(r["query_text"] or "")].append((int(r["surah_no"]), int(r["ayah_no"])))
    return dict(by_q)


def fetch_find_verse_matches_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[sqlite3.Row]:
    """Rows for preview UI, stable order."""
    return conn.execute(
        """
        SELECT
            f.id,
            f.bot1_connotation_id,
            f.source_kind,
            f.bot2_synonym_term_id,
            f.query_text,
            f.surah_no,
            f.ayah_no,
            f.created_at,
            c.connotation_text AS connotation_text_live
        FROM find_verse_matches f
        JOIN bot1_connotations c ON c.id = f.bot1_connotation_id
        WHERE f.chat_session_id = ?
        ORDER BY f.bot1_connotation_id ASC, f.source_kind ASC, f.query_text ASC,
                 f.surah_no ASC, f.ayah_no ASC, f.id ASC
        """,
        (chat_session_id,),
    ).fetchall()


@dataclass(frozen=True)
class Step3ConnotationHitRow:
    """Per-connotation hit counts from saved find_verse_matches (Bot 1 order)."""

    connotation_id: int
    topic_text: str
    connotation_text: str
    n_connotation_hits: int
    n_synonym_hits: int


@dataclass(frozen=True)
class Step3FindVersesScorecard:
    """Step 3 scorecard + bar chart: pipeline DB matches vs latest Bot 1 connotations."""

    has_bot1_run: bool
    n_connotations: int
    n_match_rows: int
    n_unique_ayahs: int
    n_connotations_with_any_hit: int
    bar_rows: tuple[Step3ConnotationHitRow, ...]


def compute_step3_find_verses_scorecard(
    conn: sqlite3.Connection, chat_session_id: str
) -> Step3FindVersesScorecard:
    """
    Aggregate saved `find_verse_matches` rows for the session against the latest Bot 1 run.
    Used for the Step 3 scorecard and hits-per-connotation chart.
    """
    b1_run = latest_bot1_pipeline_run_id(conn, chat_session_id)
    if b1_run is None:
        return Step3FindVersesScorecard(False, 0, 0, 0, 0, ())
    items = list_connotations_for_bot1_run(conn, b1_run)
    rows = fetch_find_verse_matches_for_session(conn, chat_session_id)
    by_con: dict[int, int] = defaultdict(int)
    by_syn: dict[int, int] = defaultdict(int)
    ayahs: set[tuple[int, int]] = set()
    for r in rows:
        cid = int(r["bot1_connotation_id"])
        ayahs.add((int(r["surah_no"]), int(r["ayah_no"])))
        sk = str(r["source_kind"] or "")
        if sk == "connotation":
            by_con[cid] += 1
        else:
            by_syn[cid] += 1
    bar_list: list[Step3ConnotationHitRow] = []
    n_with = 0
    for it in items:
        cid = it.bot1_connotation_id
        nc = by_con[cid]
        ns = by_syn[cid]
        if nc + ns > 0:
            n_with += 1
        bar_list.append(
            Step3ConnotationHitRow(
                cid,
                it.topic_text,
                it.connotation_text,
                nc,
                ns,
            )
        )
    return Step3FindVersesScorecard(
        True,
        len(items),
        len(rows),
        len(ayahs),
        n_with,
        tuple(bar_list),
    )


@dataclass(frozen=True)
class Step4KalimatPipelineRow:
    """One saved Find Verses hit + topic context + kalimat breakdown for the ayah."""

    find_match_id: int
    topic_text: str
    connotation_text: str
    source_kind: str
    synonym_text: str | None
    query_text: str
    surah_no: int
    ayah_no: int
    kalimat_breakdown: str


def ayah_kalimat_breakdown(conn: sqlite3.Connection, surah_no: int, ayah_no: int) -> str:
    """
    Compact per-word string for one ayah: ``1:a · b | 2:c | ...``.

    1. Prefer ``quran_tokens`` + ``quran_token_kalimah`` (morphological segments when present).
    2. If the ayah is missing in SQLite, use the same **quran.json** token lists as
       :func:`load_search_ayah_token_lists` (Find Verses can match from JSON while the DB
       has no rows for that ayah).
    3. Else use :func:`fetch_ayah_texts` and split the verse string on whitespace.
    """
    rows = conn.execute(
        """
        SELECT qt.word_no AS wn,
               qt.token_uthmani AS tok,
               COALESCE(
                   NULLIF(TRIM(GROUP_CONCAT(qk.surface, ' · ')), ''),
                   qt.token_uthmani
               ) AS kali
        FROM quran_tokens qt
        LEFT JOIN quran_token_kalimah qk ON qk.token_id = qt.id
        WHERE qt.surah_no = ? AND qt.ayah_no = ?
        GROUP BY qt.id
        ORDER BY qt.word_no
        """,
        (surah_no, ayah_no),
    ).fetchall()
    if rows:
        parts: list[str] = []
        for r in rows:
            wn = int(r["wn"])
            k = str(r["kali"] or r["tok"] or "").strip()
            parts.append(f"{wn}:{k}")
        return " | ".join(parts)

    key = (surah_no, ayah_no)
    p = _quran_json_path()
    if p.is_file():
        st = p.stat()
        ayah_map = _load_ayah_token_lists_from_quran_json(str(p), st.st_mtime_ns)
        toks = ayah_map.get(key)
        if toks:
            return " | ".join(f"{i + 1}:{t}" for i, t in enumerate(toks))

    tx = fetch_ayah_texts(conn, [key])
    full = (tx.get(key) or "").strip()
    if full:
        words = [w for w in full.replace("\n", " ").split() if w.strip()]
        if words:
            return " | ".join(f"{i + 1}:{w}" for i, w in enumerate(words))

    return (
        "(no verse text for this ayah — add project-root quran.json or import word-by-word "
        "Quran JSON into quran_tokens)"
    )


def fetch_step4_kalimat_pipeline_rows(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[Step4KalimatPipelineRow]:
    """
    Join ``find_verse_matches`` to Bot 1 topic/connotation and optional Bot 2 synonym,
    plus a per-ayah kalimat string from ``quran_token_kalimah``.
    """
    base_rows = conn.execute(
        """
        SELECT
            f.id AS find_match_id,
            t.topic_text AS topic_text,
            c.connotation_text AS connotation_text,
            f.source_kind AS source_kind,
            st.synonym_text AS synonym_text,
            f.query_text AS query_text,
            f.surah_no AS surah_no,
            f.ayah_no AS ayah_no
        FROM find_verse_matches f
        JOIN bot1_connotations c ON c.id = f.bot1_connotation_id
        JOIN bot1_topics t ON t.id = c.bot1_topic_id
        LEFT JOIN bot2_synonym_terms st ON st.id = f.bot2_synonym_term_id
        WHERE f.chat_session_id = ?
        ORDER BY t.sort_order, c.sort_order, f.source_kind ASC, f.query_text,
                 f.surah_no, f.ayah_no, f.id
        """,
        (chat_session_id,),
    ).fetchall()
    cache: dict[tuple[int, int], str] = {}
    out: list[Step4KalimatPipelineRow] = []
    for r in base_rows:
        su, ay = int(r["surah_no"]), int(r["ayah_no"])
        key = (su, ay)
        if key not in cache:
            cache[key] = ayah_kalimat_breakdown(conn, su, ay)
        syn = r["synonym_text"]
        out.append(
            Step4KalimatPipelineRow(
                find_match_id=int(r["find_match_id"]),
                topic_text=str(r["topic_text"] or ""),
                connotation_text=str(r["connotation_text"] or ""),
                source_kind=str(r["source_kind"] or ""),
                synonym_text=str(syn).strip() if syn else None,
                query_text=str(r["query_text"] or ""),
                surah_no=su,
                ayah_no=ay,
                kalimat_breakdown=cache[key],
            )
        )
    return out
