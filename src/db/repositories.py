"""Data access helpers for lexicon, Quran tokens, and mapping."""

from __future__ import annotations

import sqlite3
from typing import Any


def upsert_lexicon_root(
    conn: sqlite3.Connection,
    root_word: str,
    root_word_normalized: str,
    source_ref: str | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO lexicon_roots (root_word, root_word_normalized, source_ref)
        VALUES (?, ?, ?)
        ON CONFLICT(root_word_normalized) DO UPDATE SET
            root_word = excluded.root_word,
            source_ref = COALESCE(excluded.source_ref, lexicon_roots.source_ref)
        """,
        (root_word, root_word_normalized, source_ref),
    )
    row = conn.execute(
        "SELECT id FROM lexicon_roots WHERE root_word_normalized = ?",
        (root_word_normalized,),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def replace_entries_for_root(conn: sqlite3.Connection, root_id: int) -> None:
    conn.execute("DELETE FROM lexicon_entries WHERE root_id = ?", (root_id,))


def insert_lexicon_entry(
    conn: sqlite3.Connection,
    root_id: int,
    seq: int,
    heading_raw: str,
    heading_normalized: str | None,
    definition: str,
) -> None:
    conn.execute(
        """
        INSERT INTO lexicon_entries (root_id, seq, heading_raw, heading_normalized, definition)
        VALUES (?, ?, ?, ?, ?)
        """,
        (root_id, seq, heading_raw, heading_normalized, definition),
    )


def insert_quran_token(
    conn: sqlite3.Connection,
    surah_no: int,
    ayah_no: int,
    word_no: int,
    token_uthmani: str,
    token_plain: str,
) -> int:
    conn.execute(
        """
        INSERT INTO quran_tokens (surah_no, ayah_no, word_no, token_uthmani, token_plain)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(surah_no, ayah_no, word_no) DO UPDATE SET
            token_uthmani = excluded.token_uthmani,
            token_plain = excluded.token_plain
        """,
        (surah_no, ayah_no, word_no, token_uthmani, token_plain),
    )
    row = conn.execute(
        """
        SELECT id FROM quran_tokens
        WHERE surah_no = ? AND ayah_no = ? AND word_no = ?
        """,
        (surah_no, ayah_no, word_no),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def delete_analyses_for_token(conn: sqlite3.Connection, token_id: int) -> None:
    conn.execute("DELETE FROM token_root_analysis WHERE token_id = ?", (token_id,))


def insert_token_root_analysis(
    conn: sqlite3.Connection,
    token_id: int,
    root_id: int,
    lemma: str | None,
    pattern: str | None,
    source: str,
    confidence: float,
    is_primary: bool,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO token_root_analysis
            (token_id, root_id, lemma, pattern, source, confidence, is_primary, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(token_id, root_id) DO UPDATE SET
            lemma = excluded.lemma,
            pattern = excluded.pattern,
            source = excluded.source,
            confidence = excluded.confidence,
            is_primary = excluded.is_primary,
            notes = excluded.notes
        """,
        (
            token_id,
            root_id,
            lemma,
            pattern,
            source,
            confidence,
            1 if is_primary else 0,
            notes,
        ),
    )


def get_scraper_state(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM scraper_state WHERE id = 1").fetchone()
    return dict(row) if row else None


def upsert_scraper_state(
    conn: sqlite3.Connection,
    last_root_word_normalized: str | None,
    last_url: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO scraper_state (id, last_root_word_normalized, last_url, updated_at)
        VALUES (1, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            last_root_word_normalized = excluded.last_root_word_normalized,
            last_url = excluded.last_url,
            updated_at = datetime('now')
        """,
        (last_root_word_normalized, last_url),
    )


def fetch_all_roots_normalized(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """Return (id, root_word, root_word_normalized) for all lexicon roots."""
    rows = conn.execute(
        "SELECT id, root_word, root_word_normalized FROM lexicon_roots ORDER BY LENGTH(root_word_normalized) DESC"
    ).fetchall()
    return [(int(r["id"]), str(r["root_word"]), str(r["root_word_normalized"])) for r in rows]


def truncate_lexicon_tables(conn: sqlite3.Connection) -> None:
    """Remove all lexicon rows (entries then roots). FTS updated via triggers."""
    conn.execute("DELETE FROM lexicon_entries")
    conn.execute("DELETE FROM lexicon_roots")


def delete_all_quran_token_kalimah(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM quran_token_kalimah")


def insert_quran_token_kalimah(
    conn: sqlite3.Connection,
    token_id: int,
    kalimah_seq: int,
    surface: str,
    pos: str | None,
    morph_tags: str | None,
    source: str,
) -> None:
    conn.execute(
        """
        INSERT INTO quran_token_kalimah
            (token_id, kalimah_seq, surface, pos, morph_tags, source)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(token_id, kalimah_seq) DO UPDATE SET
            surface = excluded.surface,
            pos = excluded.pos,
            morph_tags = excluded.morph_tags,
            source = excluded.source
        """,
        (token_id, kalimah_seq, surface, pos, morph_tags, source),
    )
