"""Upload user documents to the session OpenAI vector store + SQLite."""

from __future__ import annotations

import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from src.chat.session_document_policy import (
    validate_session_upload_quota,
    validate_upload_path,
)
from src.chat.session_vector_store import ensure_session_vector_store_in_db, session_uploads_dir
from src.db.chat_pipeline import get_chat_session_openai_vector_store_id
from src.db.session_attached_documents import (
    delete_session_attached_document_row,
    get_session_attached_document,
    insert_session_attached_document,
)
from src.openai_platform.resources import (
    OpenAIAdminError,
    attach_file_to_vector_store,
    delete_file,
    delete_vector_store_file,
    retrieve_vector_store_file,
    upload_file_to_openai,
)


class SessionDocumentUploadError(Exception):
    """User-facing upload / indexing failure."""


def wait_for_vector_store_file_indexed(
    vector_store_id: str,
    file_id: str,
    *,
    timeout_s: float = 120.0,
    poll_interval_s: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    last_status = ""
    while time.monotonic() < deadline:
        try:
            row = retrieve_vector_store_file(vector_store_id, file_id)
        except OpenAIAdminError as e:
            raise SessionDocumentUploadError(str(e)) from e
        except Exception as e:
            raise SessionDocumentUploadError(f"Could not check indexing status: {e}") from e
        st = (row.get("status") or "").strip().lower()
        last_status = st or last_status
        if st == "completed":
            return
        if st in ("failed", "cancelled"):
            raise SessionDocumentUploadError(
                f"OpenAI indexing ended with status {row.get('status')!r} for file {file_id}."
            )
        time.sleep(poll_interval_s)
    raise SessionDocumentUploadError(
        f"Timed out after {timeout_s:.0f}s waiting for vector store indexing "
        f"(last status: {last_status!r})."
    )


def upload_session_user_document(
    conn: sqlite3.Connection,
    chat_session_id: str,
    session_title: str | None,
    source_path: Path,
) -> int:
    """
    Copy file locally, upload to OpenAI, attach to session vector store, wait for indexing,
    insert ``session_attached_documents`` row. Returns new row id.

    Raises SessionDocumentUploadError or OpenAIAdminError.
    """
    err = validate_upload_path(source_path)
    if err:
        raise SessionDocumentUploadError(err)
    sz = int(source_path.stat().st_size)
    qerr = validate_session_upload_quota(conn, chat_session_id, new_file_bytes=sz)
    if qerr:
        raise SessionDocumentUploadError(qerr)

    vid = ensure_session_vector_store_in_db(conn, chat_session_id, session_title)
    if not vid:
        raise SessionDocumentUploadError("Could not create or resolve session vector store.")

    uploads = session_uploads_dir(chat_session_id)
    uploads.mkdir(parents=True, exist_ok=True)
    dest_name = f"{uuid.uuid4().hex}{source_path.suffix.lower()}"
    dest_path = uploads / dest_name
    try:
        shutil.copy2(source_path, dest_path)
    except OSError as e:
        raise SessionDocumentUploadError(f"Could not copy file to session folder: {e}") from e

    fid: str | None = None
    try:
        up = upload_file_to_openai(dest_path, purpose="assistants")
        fid = str(up["id"])
        attach_file_to_vector_store(vid, fid)
        wait_for_vector_store_file_indexed(vid, fid)
    except Exception:
        if fid:
            try:
                delete_vector_store_file(vid, fid)
            except Exception:
                pass
            try:
                delete_file(fid)
            except Exception:
                pass
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    try:
        row_id = insert_session_attached_document(
            conn,
            chat_session_id=chat_session_id,
            openai_file_id=fid,
            original_filename=source_path.name,
            local_path=str(dest_path.resolve()),
            size_bytes=sz,
            commit=True,
        )
    except Exception as e:
        try:
            delete_vector_store_file(vid, fid)
        except Exception:
            pass
        try:
            delete_file(fid)
        except Exception:
            pass
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise SessionDocumentUploadError(f"Database error after upload: {e}") from e

    return row_id


def remove_session_user_document(
    conn: sqlite3.Connection,
    chat_session_id: str,
    doc_id: int,
    *,
    delete_remote_file_objects: bool = True,
) -> None:
    """Detach from vector store, optionally delete OpenAI file object, remove DB row and local file."""
    row = get_session_attached_document(conn, doc_id, chat_session_id)
    if not row:
        return
    vid = get_chat_session_openai_vector_store_id(conn, chat_session_id)
    fid = row.openai_file_id
    if vid and fid:
        try:
            delete_vector_store_file(vid, fid)
        except Exception:
            pass
        if delete_remote_file_objects:
            try:
                delete_file(fid)
            except Exception:
                pass
    try:
        Path(row.local_path).unlink(missing_ok=True)
    except OSError:
        pass
    delete_session_attached_document_row(conn, doc_id, chat_session_id, commit=True)
