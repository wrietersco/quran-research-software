"""
Chat session pipeline: one refined question per session, step runs (Bot 1, future bots).

Normalized Bot 1 storage: topics and connotations in separate tables (query-friendly).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.chat.bot1_engine import Bot1Result
from src.db.question_refiner_messages import latest_assistant_message_id

# Pipeline step identifiers (extend for Bot 3, …)
STEP_BOT1_TOPICS_CONNOTATIONS = "bot1_topics_connotations"
STEP_BOT2_ARABIC_SYNONYMS = "bot2_arabic_synonyms"


def upsert_chat_session(
    conn: sqlite3.Connection,
    chat_session_id: str,
    title: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO chat_sessions (id, title, created_at, updated_at)
        VALUES (?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            title = COALESCE(NULLIF(excluded.title, ''), chat_sessions.title),
            updated_at = datetime('now')
        """,
        (chat_session_id, title or ""),
    )


def update_chat_session_title(
    conn: sqlite3.Connection, chat_session_id: str, title: str
) -> None:
    conn.execute(
        """
        UPDATE chat_sessions SET title = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (title, chat_session_id),
    )


def get_chat_session_openai_vector_store_id(
    conn: sqlite3.Connection, chat_session_id: str
) -> str | None:
    row = conn.execute(
        "SELECT openai_vector_store_id FROM chat_sessions WHERE id = ?",
        (chat_session_id,),
    ).fetchone()
    if row is None:
        return None
    v = row["openai_vector_store_id"]
    return str(v).strip() if v else None


def set_chat_session_openai_vector_store_id(
    conn: sqlite3.Connection,
    chat_session_id: str,
    vector_store_id: str | None,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        """
        UPDATE chat_sessions
        SET openai_vector_store_id = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        ((vector_store_id.strip() if vector_store_id else None), chat_session_id),
    )
    if commit:
        conn.commit()


def upsert_session_refined_question(
    conn: sqlite3.Connection,
    chat_session_id: str,
    question_text: str,
    source_question_refiner_message_id: int | None,
) -> int:
    conn.execute(
        """
        INSERT INTO session_refined_questions (
            chat_session_id, question_text,
            source_question_refiner_message_id, finalized_at
        )
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(chat_session_id) DO UPDATE SET
            question_text = excluded.question_text,
            source_question_refiner_message_id = excluded.source_question_refiner_message_id,
            finalized_at = datetime('now')
        """,
        (chat_session_id, question_text, source_question_refiner_message_id),
    )
    row = conn.execute(
        "SELECT id FROM session_refined_questions WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchone()
    if row is None:
        raise sqlite3.IntegrityError("session_refined_questions upsert failed")
    return int(row[0])


def refined_question_id_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> int | None:
    row = conn.execute(
        "SELECT id FROM session_refined_questions WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchone()
    return int(row[0]) if row else None


def refined_question_text_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> str | None:
    row = conn.execute(
        "SELECT question_text FROM session_refined_questions WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]) if row[0] is not None else None


def _iter_connotation_entries(connotations: Any) -> list[tuple[str | None, str]]:
    """Parse Bot 1 connotations list into (slot_key, text) preserving order."""
    out: list[tuple[str | None, str]] = []
    if not isinstance(connotations, list):
        return out
    for item in connotations:
        if not isinstance(item, dict):
            continue
        for slot_key, inner in item.items():
            text = ""
            if isinstance(inner, dict):
                text = str(inner.get("text") or "")
            elif isinstance(inner, str):
                text = inner
            out.append((slot_key if slot_key else None, text))
    return out


def insert_bot1_step_run(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    session_title: str | None,
    refined: dict[str, Any],
    br: Bot1Result,
) -> int:
    """
    Persist Bot 1 under the session's refined question: one pipeline row + topics + connotations.
    Returns pipeline_step_runs.id.
    """
    analysis = br.analysis
    if not isinstance(analysis, dict):
        raise ValueError("Bot1Result.analysis must be a dict")

    upsert_chat_session(conn, chat_session_id, session_title)
    q_raw = refined.get("question")
    question_text = str(q_raw).strip() if q_raw is not None else ""
    if not question_text:
        q2 = analysis.get("question")
        question_text = str(q2).strip() if q2 is not None else ""

    asst_mid = latest_assistant_message_id(conn, chat_session_id)
    rq_id = upsert_session_refined_question(
        conn, chat_session_id, question_text, asst_mid
    )

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
            rq_id,
            STEP_BOT1_TOPICS_CONNOTATIONS,
            br.model,
            br.response_id,
            br.prompt_tokens,
            br.completion_tokens,
            br.total_tokens,
        ),
    )
    run_id = int(cur.lastrowid)

    topics_block = analysis.get("analysis")
    if not isinstance(topics_block, list):
        topics_block = []

    for ti, topic_blob in enumerate(topics_block):
        if not isinstance(topic_blob, dict):
            continue
        topic_text = str(topic_blob.get("topic") or "")
        cur = conn.execute(
            """
            INSERT INTO bot1_topics (pipeline_run_id, sort_order, topic_text)
            VALUES (?, ?, ?)
            """,
            (run_id, ti, topic_text),
        )
        topic_row_id = int(cur.lastrowid)
        pairs = _iter_connotation_entries(topic_blob.get("connotations"))
        for ci, (slot_key, ctext) in enumerate(pairs):
            conn.execute(
                """
                INSERT INTO bot1_connotations (
                    bot1_topic_id, sort_order, slot_key, connotation_text
                )
                VALUES (?, ?, ?, ?)
                """,
                (topic_row_id, ci, slot_key, ctext),
            )

    conn.commit()
    return run_id


def _rebuild_connotation_json(
    rows: list[sqlite3.Row],
) -> list[dict[str, dict[str, str]]]:
    out: list[dict[str, dict[str, str]]] = []
    for i, r in enumerate(rows):
        sk = r["slot_key"]
        key = sk if sk else f"connotation{i + 1}"
        out.append({str(key): {"text": str(r["connotation_text"] or "")}})
    return out


def fetch_latest_bot1_analysis_dict(
    conn: sqlite3.Connection, chat_session_id: str
) -> dict[str, Any] | None:
    """
    Rebuild the canonical Bot 1 JSON shape from normalized rows (latest run per session).
    """
    rq_row = conn.execute(
        "SELECT question_text FROM session_refined_questions WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchone()
    if rq_row is None:
        return None

    question = str(rq_row["question_text"] or "")
    pr = conn.execute(
        """
        SELECT id FROM pipeline_step_runs
        WHERE chat_session_id = ? AND step_key = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (chat_session_id, STEP_BOT1_TOPICS_CONNOTATIONS),
    ).fetchone()
    if pr is None:
        return {"question": question, "analysis": []}

    run_id = int(pr["id"])
    topics = conn.execute(
        """
        SELECT id, sort_order, topic_text FROM bot1_topics
        WHERE pipeline_run_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (run_id,),
    ).fetchall()

    analysis_list: list[dict[str, Any]] = []
    for t in topics:
        tid = int(t["id"])
        crows = conn.execute(
            """
            SELECT slot_key, connotation_text FROM bot1_connotations
            WHERE bot1_topic_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (tid,),
        ).fetchall()
        analysis_list.append(
            {
                "topic": str(t["topic_text"] or ""),
                "connotations": _rebuild_connotation_json(list(crows)),
            }
        )

    return {"question": question, "analysis": analysis_list}


def delete_chat_session_pipeline(conn: sqlite3.Connection, chat_session_id: str) -> None:
    """Remove session row; CASCADE drops refined question, pipeline runs, Bot 1 rows."""
    conn.execute("DELETE FROM chat_sessions WHERE id = ?", (chat_session_id,))
    conn.commit()


def sync_refined_question_from_chat(
    conn: sqlite3.Connection,
    chat_session_id: str,
    session_title: str | None,
    refined: dict[str, Any],
    source_question_refiner_message_id: int | None,
    *,
    commit: bool = True,
) -> None:
    """When refiner produces <<<REFINED_JSON>>>, record the single finalized question for the session."""
    upsert_chat_session(conn, chat_session_id, session_title)
    q = refined.get("question")
    question_text = str(q).strip() if q is not None else ""
    if not question_text:
        return
    upsert_session_refined_question(
        conn, chat_session_id, question_text, source_question_refiner_message_id
    )
    if commit:
        conn.commit()
