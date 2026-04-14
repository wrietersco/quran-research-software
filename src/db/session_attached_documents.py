"""User-uploaded session documents (Refine + pipeline vector store)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionAttachedDocumentRow:
    id: int
    chat_session_id: str
    openai_file_id: str
    original_filename: str
    local_path: str
    size_bytes: int


def list_session_attached_documents(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[SessionAttachedDocumentRow]:
    rows = conn.execute(
        """
        SELECT id, chat_session_id, openai_file_id, original_filename, local_path, size_bytes
        FROM session_attached_documents
        WHERE chat_session_id = ?
        ORDER BY id ASC
        """,
        (chat_session_id,),
    ).fetchall()
    return [
        SessionAttachedDocumentRow(
            id=int(r["id"]),
            chat_session_id=str(r["chat_session_id"]),
            openai_file_id=str(r["openai_file_id"]),
            original_filename=str(r["original_filename"]),
            local_path=str(r["local_path"]),
            size_bytes=int(r["size_bytes"]),
        )
        for r in rows
    ]


def count_session_attached_documents(
    conn: sqlite3.Connection, chat_session_id: str
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM session_attached_documents WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchone()
    return int(row["c"]) if row else 0


def sum_session_attached_bytes(conn: sqlite3.Connection, chat_session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS s FROM session_attached_documents WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchone()
    return int(row["s"]) if row else 0


def get_session_attached_document(
    conn: sqlite3.Connection, doc_id: int, chat_session_id: str
) -> SessionAttachedDocumentRow | None:
    r = conn.execute(
        """
        SELECT id, chat_session_id, openai_file_id, original_filename, local_path, size_bytes
        FROM session_attached_documents
        WHERE id = ? AND chat_session_id = ?
        """,
        (doc_id, chat_session_id),
    ).fetchone()
    if not r:
        return None
    return SessionAttachedDocumentRow(
        id=int(r["id"]),
        chat_session_id=str(r["chat_session_id"]),
        openai_file_id=str(r["openai_file_id"]),
        original_filename=str(r["original_filename"]),
        local_path=str(r["local_path"]),
        size_bytes=int(r["size_bytes"]),
    )


def insert_session_attached_document(
    conn: sqlite3.Connection,
    *,
    chat_session_id: str,
    openai_file_id: str,
    original_filename: str,
    local_path: str,
    size_bytes: int,
    commit: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO session_attached_documents (
            chat_session_id, openai_file_id, original_filename, local_path, size_bytes
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (chat_session_id, openai_file_id, original_filename, local_path, size_bytes),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def delete_session_attached_document_row(
    conn: sqlite3.Connection, doc_id: int, chat_session_id: str, *, commit: bool = True
) -> bool:
    cur = conn.execute(
        "DELETE FROM session_attached_documents WHERE id = ? AND chat_session_id = ?",
        (doc_id, chat_session_id),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


def list_openai_file_ids_for_session_attached(
    conn: sqlite3.Connection, chat_session_id: str
) -> list[str]:
    rows = conn.execute(
        "SELECT openai_file_id FROM session_attached_documents WHERE chat_session_id = ?",
        (chat_session_id,),
    ).fetchall()
    return [str(r["openai_file_id"]) for r in rows if r["openai_file_id"]]
