"""Tests for session document upload validation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.chat.session_document_policy import (
    ALLOWED_FILE_SUFFIXES,
    MAX_ATTACHED_FILES_PER_SESSION,
    validate_session_upload_quota,
    validate_upload_path,
)
from src.db.session_attached_documents import insert_session_attached_document


def test_validate_upload_path_allowed_txt(tmp_path: Path) -> None:
    p = tmp_path / "notes.txt"
    p.write_text("hello", encoding="utf-8")
    assert validate_upload_path(p) is None


def test_validate_upload_path_rejects_bad_extension(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"\x00\x01")
    err = validate_upload_path(p)
    assert err is not None
    assert "Unsupported" in err


def test_validate_upload_path_rejects_empty(tmp_path: Path) -> None:
    p = tmp_path / "empty.txt"
    p.write_text("", encoding="utf-8")
    err = validate_upload_path(p)
    assert err is not None
    assert "empty" in err.lower()


def test_validate_upload_path_rejects_missing() -> None:
    err = validate_upload_path(Path("/nonexistent/path/no-file-here.pdf"))
    assert err is not None


def test_allowed_suffixes_include_common_docs() -> None:
    for suf in (".pdf", ".txt", ".md", ".docx", ".json", ".csv"):
        assert suf in ALLOWED_FILE_SUFFIXES


def test_validate_session_upload_quota_max_files() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE session_attached_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            openai_file_id TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            local_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("INSERT INTO chat_sessions (id, title) VALUES ('s1', 't')")
    for i in range(MAX_ATTACHED_FILES_PER_SESSION):
        insert_session_attached_document(
            conn,
            chat_session_id="s1",
            openai_file_id=f"f{i}",
            original_filename=f"n{i}.txt",
            local_path=f"/tmp/{i}",
            size_bytes=100,
            commit=True,
        )
    err = validate_session_upload_quota(conn, "s1", new_file_bytes=1)
    assert err is not None
    assert "Maximum" in err


def test_validate_session_upload_quota_total_bytes() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE session_attached_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            openai_file_id TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            local_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("INSERT INTO chat_sessions (id, title) VALUES ('s2', 't')")
    insert_session_attached_document(
        conn,
        chat_session_id="s2",
        openai_file_id="f1",
        original_filename="a.txt",
        local_path="/tmp/a",
        size_bytes=499 * 1024 * 1024,
        commit=True,
    )
    err = validate_session_upload_quota(conn, "s2", new_file_bytes=3 * 1024 * 1024)
    assert err is not None
    assert "exceed" in err.lower()
