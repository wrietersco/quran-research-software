"""Persist Question refiner chat turns (mirror of session JSON) for querying and Bot 1 linkage."""

from __future__ import annotations

import sqlite3


def insert_question_refiner_message(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    session_title: str | None,
    role: str,
    bot_name: str,
    content: str,
    model: str | None = None,
    response_id: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    commit: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO question_refiner_messages (
            chat_session_id, session_title, role, bot_name, content,
            model, response_id, prompt_tokens, completion_tokens, total_tokens
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_session_id,
            session_title,
            role,
            bot_name,
            content,
            model,
            response_id,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        ),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def latest_assistant_message_id(
    conn: sqlite3.Connection, chat_session_id: str
) -> int | None:
    cur = conn.execute(
        """
        SELECT id FROM question_refiner_messages
        WHERE chat_session_id = ? AND role = 'assistant'
        ORDER BY id DESC
        LIMIT 1
        """,
        (chat_session_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return int(row[0])


def delete_messages_for_session(conn: sqlite3.Connection, chat_session_id: str) -> None:
    conn.execute(
        """
        UPDATE bot1_analysis_runs
        SET question_refiner_assistant_message_id = NULL
        WHERE chat_session_id = ?
        """,
        (chat_session_id,),
    )
    conn.execute(
        "DELETE FROM question_refiner_messages WHERE chat_session_id = ?",
        (chat_session_id,),
    )
    conn.commit()
