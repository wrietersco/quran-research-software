"""Create and persist per-session OpenAI vector stores for Step 6."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from src.config import PROJECT_ROOT, get_db_path
from src.db.chat_pipeline import (
    get_chat_session_openai_vector_store_id,
    set_chat_session_openai_vector_store_id,
    upsert_chat_session,
)
from src.db.connection import connect
from src.db.step6_report import list_openai_report_file_ids_for_session
from src.openai_platform.resources import (
    OpenAIAdminError,
    create_vector_store,
    delete_file,
    delete_vector_store,
    delete_vector_store_file,
)


def session_data_root(chat_session_id: str) -> Path:
    """Root directory for all on-disk artifacts for one chat session."""
    return PROJECT_ROOT / "data" / "sessions" / chat_session_id


def session_knowledge_dir(chat_session_id: str) -> Path:
    return session_data_root(chat_session_id) / "knowledge"


def session_reports_dir(chat_session_id: str) -> Path:
    return session_data_root(chat_session_id) / "reports"


def delete_session_local_data_directory(chat_session_id: str) -> None:
    """Remove ``data/sessions/<id>/`` (knowledge chunks, reports, etc.). Best-effort."""
    import shutil

    root = session_data_root(chat_session_id)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def ensure_session_vector_store_in_db(
    conn: sqlite3.Connection,
    chat_session_id: str,
    session_title: str | None,
) -> str | None:
    """
    Ensure ``chat_sessions`` row exists, then return the session vector store id,
    creating one on OpenAI and persisting when missing (Step 6 backward compatibility
    for sessions created before per-session vector stores).

    Raises OpenAIAdminError on API/key failure or if the id cannot be persisted.
    """
    upsert_chat_session(conn, chat_session_id, session_title)
    existing = get_chat_session_openai_vector_store_id(conn, chat_session_id)
    if existing:
        return existing
    label = (session_title or "").strip() or chat_session_id[:12]
    vs = create_vector_store(name=f"quran-session-{label}"[:256])
    vid = str(vs["id"])
    set_chat_session_openai_vector_store_id(
        conn, chat_session_id, vid, commit=True
    )
    verified = get_chat_session_openai_vector_store_id(conn, chat_session_id)
    if not verified:
        raise OpenAIAdminError(
            "Vector store was created but could not be saved on the session row "
            "(check database / chat_sessions)."
        )
    return verified


def create_session_vector_store_async(
    chat_session_id: str,
    session_title: str | None,
    *,
    on_success: Callable[[str], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Background-friendly: open own DB connection; invoke callbacks on Tk thread."""

    def _work() -> None:
        try:
            conn = connect(get_db_path())
            try:
                vid = ensure_session_vector_store_in_db(
                    conn, chat_session_id, session_title
                )
            finally:
                conn.close()
        except (OpenAIAdminError, OSError, sqlite3.Error) as e:
            if on_error:
                on_error(e)
            return
        if on_success and vid:
            on_success(vid)

    import threading

    threading.Thread(target=_work, daemon=True).start()


def detach_and_delete_openai_knowledge_files(
    vector_store_id: str,
    openai_file_ids: list[str],
    *,
    delete_remote_file_objects: bool = True,
) -> None:
    for fid in openai_file_ids:
        if not fid:
            continue
        try:
            delete_vector_store_file(vector_store_id, fid)
        except Exception:
            pass
        if delete_remote_file_objects:
            try:
                delete_file(fid)
            except Exception:
                pass


def cleanup_openai_session_resources_before_db_delete(
    conn: sqlite3.Connection, chat_session_id: str
) -> None:
    """Detach uploaded knowledge files and delete the session vector store (best-effort)."""
    vid = get_chat_session_openai_vector_store_id(conn, chat_session_id)
    if not vid:
        return
    rows = conn.execute(
        "SELECT openai_file_id FROM step6_knowledge_files WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchall()
    kf = [str(r["openai_file_id"]) for r in rows if r["openai_file_id"]]
    rf = list_openai_report_file_ids_for_session(conn, chat_session_id)
    fids = list(dict.fromkeys(kf + rf))
    detach_and_delete_openai_knowledge_files(vid, fids)
    try:
        delete_vector_store(vid)
    except Exception:
        pass
