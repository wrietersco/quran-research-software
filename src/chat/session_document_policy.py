"""Validation limits for session document uploads (OpenAI file_search / vector store)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

# OpenAI Files API / vector store typical per-file ceiling (see platform docs).
MAX_UPLOAD_FILE_BYTES = 512 * 1024 * 1024

# App caps (per session).
MAX_ATTACHED_FILES_PER_SESSION = 20
MAX_TOTAL_ATTACHED_BYTES_PER_SESSION = 500 * 1024 * 1024

# Suffixes commonly supported for Assistants file_search (lowercase).
ALLOWED_FILE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".c",
        ".cpp",
        ".cs",
        ".css",
        ".csv",
        ".doc",
        ".docx",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".htm",
        ".java",
        ".jpg",
        ".jpeg",
        ".js",
        ".json",
        ".kt",
        ".md",
        ".pdf",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".swift",
        ".tex",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
    }
)


def normalized_suffix(path: Path) -> str:
    return path.suffix.lower()


def validate_upload_path(path: Path) -> str | None:
    """
    Return an error message string if invalid, else None.
    Does not check session counts (use ``validate_session_upload_quota``).
    """
    if not path.is_file():
        return "Not a file or file does not exist."
    suf = normalized_suffix(path)
    if suf not in ALLOWED_FILE_SUFFIXES:
        return (
            f"Unsupported file type ({path.suffix or '(no extension)'}). "
            f"Allowed: {', '.join(sorted(ALLOWED_FILE_SUFFIXES))}"
        )
    try:
        sz = path.stat().st_size
    except OSError as e:
        return f"Could not read file size: {e}"
    if sz <= 0:
        return "File is empty."
    if sz > MAX_UPLOAD_FILE_BYTES:
        return f"File too large ({sz} bytes). Maximum is {MAX_UPLOAD_FILE_BYTES} bytes per file."
    return None


def validate_session_upload_quota(
    conn: sqlite3.Connection,
    chat_session_id: str,
    *,
    new_file_bytes: int,
) -> str | None:
    """Return error message if adding ``new_file_bytes`` would exceed session caps."""
    from src.db.session_attached_documents import (
        count_session_attached_documents,
        sum_session_attached_bytes,
    )

    n = count_session_attached_documents(conn, chat_session_id)
    if n >= MAX_ATTACHED_FILES_PER_SESSION:
        return (
            f"Maximum {MAX_ATTACHED_FILES_PER_SESSION} attached documents per session "
            "(remove one before adding more)."
        )
    total = sum_session_attached_bytes(conn, chat_session_id)
    if total + int(new_file_bytes) > MAX_TOTAL_ATTACHED_BYTES_PER_SESSION:
        return (
            f"Total attachment size would exceed {MAX_TOTAL_ATTACHED_BYTES_PER_SESSION} bytes "
            "for this session (remove files or use smaller documents)."
        )
    return None
