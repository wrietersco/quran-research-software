"""Per-word rows linked to ``find_verse_matches`` for session/topic/connotation-scoped iteration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class FindMatchWordRow:
    id: int
    find_match_id: int
    token_id: int
    word_no: int
    work_status: str
    work_payload: str | None
    work_error: str | None


def populate_find_match_word_rows_for_session(
    conn: sqlite3.Connection, chat_session_id: str
) -> int:
    """
    Insert one row per ``quran_tokens`` word for each saved match in the session.

    ``find_match_id`` already encodes session, connotation (→ topic), query, and verse.
    """
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO find_match_word_rows (
            find_match_id, token_id, word_no, work_status
        )
        SELECT f.id, qt.id, qt.word_no, 'pending'
        FROM find_verse_matches f
        JOIN quran_tokens qt
            ON qt.surah_no = f.surah_no AND qt.ayah_no = f.ayah_no
        WHERE f.chat_session_id = ?
        """,
        (chat_session_id,),
    )
    return int(cur.rowcount or 0)


def backfill_find_match_word_rows_missing(conn: sqlite3.Connection) -> None:
    """
    Link any ``find_verse_matches`` row that has no child word rows yet (upgrade / repair).
    Safe to run repeatedly.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO find_match_word_rows (
            find_match_id, token_id, word_no, work_status
        )
        SELECT f.id, qt.id, qt.word_no, 'pending'
        FROM find_verse_matches f
        JOIN quran_tokens qt
            ON qt.surah_no = f.surah_no AND qt.ayah_no = f.ayah_no
        WHERE NOT EXISTS (
            SELECT 1 FROM find_match_word_rows w WHERE w.find_match_id = f.id
        )
        """
    )


def fetch_token_ids_for_find_match(
    conn: sqlite3.Connection, find_match_id: int
) -> list[int]:
    rows = conn.execute(
        """
        SELECT token_id
        FROM find_match_word_rows
        WHERE find_match_id = ?
        ORDER BY word_no ASC, id ASC
        """,
        (find_match_id,),
    ).fetchall()
    return [int(r["token_id"]) for r in rows]


def fetch_find_match_word_rows_for_match(
    conn: sqlite3.Connection, find_match_id: int
) -> list[FindMatchWordRow]:
    rows = conn.execute(
        """
        SELECT id, find_match_id, token_id, word_no, work_status, work_payload, work_error
        FROM find_match_word_rows
        WHERE find_match_id = ?
        ORDER BY word_no ASC, id ASC
        """,
        (find_match_id,),
    ).fetchall()
    out: list[FindMatchWordRow] = []
    for r in rows:
        out.append(
            FindMatchWordRow(
                id=int(r["id"]),
                find_match_id=int(r["find_match_id"]),
                token_id=int(r["token_id"]),
                word_no=int(r["word_no"]),
                work_status=str(r["work_status"] or "pending"),
                work_payload=str(r["work_payload"]) if r["work_payload"] else None,
                work_error=str(r["work_error"]) if r["work_error"] else None,
            )
        )
    return out


def update_find_match_word_work(
    conn: sqlite3.Connection,
    row_id: int,
    *,
    status: str,
    payload: str | None = None,
    error: str | None = None,
) -> None:
    """Update iterative-work fields on one word row (caller may ``commit``)."""
    conn.execute(
        """
        UPDATE find_match_word_rows
        SET work_status = ?,
            work_payload = ?,
            work_error = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, payload, error, row_id),
    )
