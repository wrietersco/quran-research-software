"""Import project-root quran.json (verse-per-row) into quran_verses and quran_tokens."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..normalize.arabic import normalize_arabic


@dataclass(frozen=True)
class QuranRootJsonImportStats:
    verses_upserted: int
    tokens_upserted: int


def _iter_verse_rows(data: object):
    """Yield (surah_no, ayah_no, text) from mushaf-style JSON."""
    if isinstance(data, dict):
        groups = data.values()
    elif isinstance(data, list):
        groups = [data]
    else:
        return
    for group in groups:
        if not isinstance(group, list):
            continue
        for row in group:
            if not isinstance(row, dict):
                continue
            surah = row.get("chapter", row.get("surah", row.get("surah_no")))
            ayah = row.get("verse", row.get("ayah", row.get("ayah_no")))
            text = row.get("text", "")
            if surah is None or ayah is None:
                continue
            try:
                su, ay = int(surah), int(ayah)
            except (TypeError, ValueError):
                continue
            yield su, ay, str(text or "").strip()


def import_quran_root_json(
    conn,
    path: Path,
    *,
    source_ref: str | None = None,
) -> QuranRootJsonImportStats:
    """
    Parse ``quran.json``-shaped data: top-level map of surah → list of
    ``{ "chapter", "verse", "text" }``.

    - Upserts every verse into ``quran_verses``.
    - Splits each ``text`` on ASCII whitespace into words and upserts ``quran_tokens``
      (``word_no`` = 1..n) with ``token_plain = normalize_arabic(token_uthmani)``.
    """
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    data = json.loads(raw)
    ref = source_ref or path.name

    verse_rows: list[tuple[int, int, str, str]] = []
    token_batch: list[tuple[int, int, int, str, str]] = []

    for su, ay, vtext in _iter_verse_rows(data):
        if not vtext:
            continue
        verse_rows.append((su, ay, vtext, ref))
        words = [w for w in vtext.replace("\n", " ").split() if w.strip()]
        for i, w in enumerate(words, start=1):
            plain = normalize_arabic(w)
            token_batch.append((su, ay, i, w, plain))

    conn.executemany(
        """
        INSERT INTO quran_verses (surah_no, ayah_no, verse_text, source_ref)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(surah_no, ayah_no) DO UPDATE SET
            verse_text = excluded.verse_text,
            source_ref = excluded.source_ref
        """,
        verse_rows,
    )

    conn.executemany(
        """
        INSERT INTO quran_tokens (surah_no, ayah_no, word_no, token_uthmani, token_plain)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(surah_no, ayah_no, word_no) DO UPDATE SET
            token_uthmani = excluded.token_uthmani,
            token_plain = excluded.token_plain
        """,
        token_batch,
    )

    return QuranRootJsonImportStats(
        verses_upserted=len(verse_rows),
        tokens_upserted=len(token_batch),
    )
