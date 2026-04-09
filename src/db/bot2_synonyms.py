"""Bot 2: Arabic synonyms per Bot 1 connotation, linked via pipeline_step_runs."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from src.chat.bot2_engine import Bot2Result
from src.db.chat_pipeline import STEP_BOT1_TOPICS_CONNOTATIONS, STEP_BOT2_ARABIC_SYNONYMS


@dataclass(frozen=True)
class ConnotationWorkItem:
    bot1_connotation_id: int
    connotation_text: str
    topic_text: str


def latest_bot1_pipeline_run_id(
    conn: sqlite3.Connection, chat_session_id: str
) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM pipeline_step_runs
        WHERE chat_session_id = ? AND step_key = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (chat_session_id, STEP_BOT1_TOPICS_CONNOTATIONS),
    ).fetchone()
    return int(row[0]) if row else None


def list_connotations_for_bot1_run(
    conn: sqlite3.Connection, bot1_pipeline_run_id: int
) -> list[ConnotationWorkItem]:
    rows = conn.execute(
        """
        SELECT c.id AS cid, c.connotation_text, t.topic_text
        FROM bot1_connotations c
        JOIN bot1_topics t ON t.id = c.bot1_topic_id
        WHERE t.pipeline_run_id = ?
        ORDER BY t.sort_order ASC, t.id ASC, c.sort_order ASC, c.id ASC
        """,
        (bot1_pipeline_run_id,),
    ).fetchall()
    out: list[ConnotationWorkItem] = []
    for r in rows:
        out.append(
            ConnotationWorkItem(
                bot1_connotation_id=int(r["cid"]),
                connotation_text=str(r["connotation_text"] or ""),
                topic_text=str(r["topic_text"] or ""),
            )
        )
    return out


def insert_bot2_synonym_pipeline(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    refined_question_id: int,
    item: ConnotationWorkItem,
    br: Bot2Result,
) -> int:
    """Insert pipeline_step_run + bot2_synonym_runs + terms. Returns pipeline_run id."""
    cur = conn.execute(
        """
        INSERT INTO pipeline_step_runs (
            chat_session_id, refined_question_id, step_key,
            model, openai_response_id,
            prompt_tokens, completion_tokens, total_tokens
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_session_id,
            refined_question_id,
            STEP_BOT2_ARABIC_SYNONYMS,
            br.model,
            br.response_id,
            br.prompt_tokens,
            br.completion_tokens,
            br.total_tokens,
        ),
    )
    pr_id = int(cur.lastrowid)
    cur = conn.execute(
        """
        INSERT INTO bot2_synonym_runs (
            pipeline_run_id, bot1_connotation_id,
            connotation_text_snapshot, topic_text_snapshot,
            model, openai_response_id,
            prompt_tokens, completion_tokens, total_tokens
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pr_id,
            item.bot1_connotation_id,
            item.connotation_text,
            item.topic_text or None,
            br.model,
            br.response_id,
            br.prompt_tokens,
            br.completion_tokens,
            br.total_tokens,
        ),
    )
    wr_id = int(cur.lastrowid)
    pos = 0
    for syn in br.synonyms:
        s = str(syn).strip()
        if not s:
            continue
        conn.execute(
            """
            INSERT INTO bot2_synonym_terms (bot2_synonym_run_id, sort_order, synonym_text)
            VALUES (?, ?, ?)
            """,
            (wr_id, pos, s),
        )
        pos += 1
    conn.commit()
    return pr_id


def bot1_connotation_ids_with_bot2_for_bot1_run(
    conn: sqlite3.Connection,
    chat_session_id: str,
    bot1_pipeline_run_id: int,
) -> set[int]:
    """
    Connotation ids that already have at least one Bot 2 synonym run saved for this session,
    where the connotation belongs to the given Bot 1 pipeline run (topic.pipeline_run_id).
    """
    rows = conn.execute(
        """
        SELECT DISTINCT bsr.bot1_connotation_id AS cid
        FROM bot2_synonym_runs bsr
        JOIN pipeline_step_runs pr ON pr.id = bsr.pipeline_run_id
        JOIN bot1_connotations c ON c.id = bsr.bot1_connotation_id
        JOIN bot1_topics t ON t.id = c.bot1_topic_id
        WHERE pr.chat_session_id = ?
          AND pr.step_key = ?
          AND t.pipeline_run_id = ?
        """,
        (chat_session_id, STEP_BOT2_ARABIC_SYNONYMS, int(bot1_pipeline_run_id)),
    ).fetchall()
    return {int(r["cid"]) for r in rows}


def fetch_latest_bot2_display_lines(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[str]:
    """Human-readable lines: connotation → synonyms (latest run per connotation)."""
    runs = conn.execute(
        """
        SELECT bsr.id AS wrid, bsr.bot1_connotation_id, bsr.connotation_text_snapshot
        FROM bot2_synonym_runs bsr
        JOIN pipeline_step_runs pr ON pr.id = bsr.pipeline_run_id
        WHERE pr.chat_session_id = ? AND pr.step_key = ?
        ORDER BY bsr.id DESC
        """,
        (chat_session_id, STEP_BOT2_ARABIC_SYNONYMS),
    ).fetchall()
    chosen: dict[int, int] = {}
    for r in runs:
        cid = int(r["bot1_connotation_id"])
        if cid not in chosen:
            chosen[cid] = int(r["wrid"])
    if not chosen:
        return []
    lines: list[str] = []
    for cid in sorted(chosen.keys()):
        wrid = chosen[cid]
        snap = next(
            str(r["connotation_text_snapshot"] or "")
            for r in runs
            if int(r["wrid"]) == wrid
        )
        terms = conn.execute(
            """
            SELECT synonym_text FROM bot2_synonym_terms
            WHERE bot2_synonym_run_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (wrid,),
        ).fetchall()
        syns = [str(t["synonym_text"] or "") for t in terms if str(t["synonym_text"] or "")]
        lines.append(f"[connotation id={cid}] {snap}")
        lines.append("  → " + ("، ".join(syns) if syns else "(no synonyms)"))
        lines.append("")
    return lines
