"""Orchestrate full session deletion: OpenAI resources, SQLite, then local session folder."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from src.chat.session_vector_store import (
    cleanup_openai_session_resources_before_db_delete,
    delete_session_local_data_directory,
)
from src.chat.sessions_store import ChatSessionsStore
from src.config import get_db_path
from src.db.bot1_analysis import delete_bot1_analysis_runs_for_session
from src.db.chat_pipeline import delete_chat_session_pipeline
from src.db.connection import connect
from src.db.question_refiner_messages import delete_messages_for_session

# Labels for UI progress (same order as run_session_deletion_desktop steps).
SESSION_DELETE_STEP_LABELS: tuple[str, ...] = (
    "Local chat list (JSON)",
    "OpenAI: vector store and uploaded files",
    "Database: legacy Bot 1 snapshots",
    "Database: session row and linked pipeline data",
    "Database: refiner conversation messages",
    "Local folder (data/sessions/…)",
)

SessionDeleteProgressCallback = Callable[[int, int, str, str], None]
"""Args: step_index, total_steps, step_label, phase where phase is begin|end|error."""


def delete_session_database_side(conn: sqlite3.Connection, chat_session_id: str) -> None:
    """
    Delete one session everywhere in the DB and on OpenAI:
    detach/delete vector store files, legacy Bot 1 snapshots, ``chat_sessions`` (CASCADE),
    and question refiner messages.
    """
    cleanup_openai_session_resources_before_db_delete(conn, chat_session_id)
    delete_bot1_analysis_runs_for_session(conn, chat_session_id)
    delete_chat_session_pipeline(conn, chat_session_id)
    delete_messages_for_session(conn, chat_session_id)


def delete_session_files_on_disk(chat_session_id: str) -> None:
    """Remove ``data/sessions/<chat_session_id>/`` after database deletion succeeds."""
    delete_session_local_data_directory(chat_session_id)


def run_session_deletion_desktop(
    store: ChatSessionsStore,
    chat_session_id: str,
    on_step: SessionDeleteProgressCallback | None,
) -> None:
    """
    Full desktop delete: JSON store, phased DB/OpenAI steps, local folder.
    Invokes ``on_step`` before and after each step (if provided) for progress UI.
    """
    total = len(SESSION_DELETE_STEP_LABELS)
    labels = SESSION_DELETE_STEP_LABELS

    def _p(i: int, phase: str) -> None:
        if on_step:
            on_step(i, total, labels[i], phase)

    _p(0, "begin")
    try:
        store.delete_session(chat_session_id)
    except Exception:
        _p(0, "error")
        raise
    _p(0, "end")

    conn = connect(get_db_path())
    try:
        _p(1, "begin")
        try:
            cleanup_openai_session_resources_before_db_delete(conn, chat_session_id)
        except Exception:
            _p(1, "error")
            raise
        _p(1, "end")

        _p(2, "begin")
        try:
            delete_bot1_analysis_runs_for_session(conn, chat_session_id)
        except Exception:
            _p(2, "error")
            raise
        _p(2, "end")

        _p(3, "begin")
        try:
            delete_chat_session_pipeline(conn, chat_session_id)
        except Exception:
            _p(3, "error")
            raise
        _p(3, "end")

        _p(4, "begin")
        try:
            delete_messages_for_session(conn, chat_session_id)
        except Exception:
            _p(4, "error")
            raise
        _p(4, "end")
    finally:
        conn.close()

    _p(5, "begin")
    try:
        delete_session_files_on_disk(chat_session_id)
    except Exception:
        _p(5, "error")
        raise
    _p(5, "end")
