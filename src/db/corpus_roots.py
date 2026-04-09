"""Derive Quranic Arabic Corpus stem roots from ``quran_token_kalimah.morph_tags``."""

from __future__ import annotations

import re
from dataclasses import dataclass

# FEATURES column contains e.g. STEM|POS:N|LEM:{som|ROOT:smw|M|GEN
_ROOT_RE = re.compile(r"ROOT:([^|]+)")


def root_buckwalter_from_morph_tags(morph_tags: str | None) -> str | None:
    """Return the Buckwalter root string from one segment's ``morph_tags``, if any."""
    if not morph_tags or not str(morph_tags).strip():
        return None
    m = _ROOT_RE.search(str(morph_tags))
    return m.group(1).strip() if m else None


def extract_corpus_root_buckwalter(morph_tags_list: list[str | None]) -> str | None:
    """
    Pick one Buckwalter root string per word.

    Prefer ``ROOT:`` on a segment whose tags indicate a stem (``STEM|``); otherwise
    first ``ROOT:`` on any segment.
    """
    stem_rows: list[str] = []
    other_rows: list[str] = []
    for mt in morph_tags_list:
        if not mt or not str(mt).strip():
            continue
        s = str(mt)
        if "STEM|" in s or s.startswith("STEM|"):
            stem_rows.append(s)
        else:
            other_rows.append(s)
    for s in stem_rows + other_rows:
        m = _ROOT_RE.search(s)
        if m:
            return m.group(1).strip()
    return None


def buckwalter_root_to_arabic(root_bw: str | None) -> str | None:
    """Best-effort Arabic display for a short Buckwalter root (may fail for odd tokens)."""
    if not root_bw or not root_bw.strip():
        return None
    t = root_bw.strip()
    if any("\u0600" <= c <= "\u06ff" for c in t):
        return t
    try:
        from pyarabic.trans import tim2utf8

        return tim2utf8(t)
    except Exception:
        return None


@dataclass(frozen=True)
class CorpusRootPopulateStats:
    tokens_total: int
    rows_inserted: int
    with_root_bw: int
    with_root_ar: int


def populate_quran_token_corpus_roots(conn) -> CorpusRootPopulateStats:
    """
    Rebuild ``quran_token_corpus_root``: one row per ``quran_tokens`` row.

    ``root_buckwalter`` / ``root_arabic`` are NULL when no ``ROOT:`` appears in kalimah tags.
    """
    conn.execute("DELETE FROM quran_token_corpus_root")
    tokens = conn.execute(
        """
        SELECT id, surah_no, ayah_no, word_no
        FROM quran_tokens
        ORDER BY surah_no, ayah_no, word_no
        """
    ).fetchall()
    rows_out: list[tuple[int, int, int, int, str | None, str | None, str]] = []
    with_bw = 0
    with_ar = 0
    for t in tokens:
        tid = int(t["id"])
        k = conn.execute(
            """
            SELECT morph_tags
            FROM quran_token_kalimah
            WHERE token_id = ?
            ORDER BY kalimah_seq
            """,
            (tid,),
        ).fetchall()
        tags = [r["morph_tags"] for r in k]
        root_bw = extract_corpus_root_buckwalter(tags)
        root_ar = buckwalter_root_to_arabic(root_bw)
        if root_bw:
            with_bw += 1
        if root_ar:
            with_ar += 1
        rows_out.append(
            (
                tid,
                int(t["surah_no"]),
                int(t["ayah_no"]),
                int(t["word_no"]),
                root_bw,
                root_ar,
                "corpus_morphology",
            )
        )
    conn.executemany(
        """
        INSERT INTO quran_token_corpus_root
            (token_id, surah_no, ayah_no, word_no, root_buckwalter, root_arabic, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows_out,
    )
    return CorpusRootPopulateStats(
        tokens_total=len(tokens),
        rows_inserted=len(rows_out),
        with_root_bw=with_bw,
        with_root_ar=with_ar,
    )
