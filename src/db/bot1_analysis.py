"""Persist Bot 1 (topics/connotations) analysis runs."""

from __future__ import annotations

import sqlite3


def insert_bot1_run(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str | None,
    session_title: str | None = None,
    question_refiner_assistant_message_id: int | None = None,
    refined_question_json: str,
    analysis_json: str,
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO bot1_analysis_runs (
            chat_session_id, session_title, question_refiner_assistant_message_id,
            refined_question_json, analysis_json,
            model, prompt_tokens, completion_tokens, total_tokens
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_session_id,
            session_title,
            question_refiner_assistant_message_id,
            refined_question_json,
            analysis_json,
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)
