"""Query helpers for verse → words → mapped roots → lexicon entry headings and definitions."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from src.db.corpus_roots import buckwalter_root_to_arabic, root_buckwalter_from_morph_tags
from src.normalize.arabic import normalize_arabic


@dataclass(frozen=True)
class LexiconHeading:
    seq: int
    label: str  # heading_normalized or heading_raw
    definition: str  # full Lane / lexicon body text


@dataclass(frozen=True)
class KalimahSegment:
    """One morphological segment (kalimah) inside an orthographic Quran word."""

    surface: str
    pos: str | None


@dataclass(frozen=True)
class MorphemeRootRow:
    """One kalimah segment with optional Quranic Arabic Corpus ``ROOT:`` from ``morph_tags``."""

    kalimah_seq: int
    surface: str
    pos: str | None
    root_buckwalter: str | None
    root_arabic: str | None


@dataclass(frozen=True)
class WordMorphemeRoots:
    word_no: int
    token_uthmani: str
    morphemes: tuple[MorphemeRootRow, ...]


@dataclass(frozen=True)
class VerseWordNode:
    token_id: int
    word_no: int
    token_uthmani: str
    root_word: str | None
    root_id: int | None
    entry_headings: tuple[LexiconHeading, ...]
    kalimat: tuple[KalimahSegment, ...]


def list_surahs_with_tokens(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT DISTINCT surah_no FROM quran_tokens ORDER BY surah_no"
    ).fetchall()
    return [int(r[0]) for r in rows]


def _load_kalimat_batch(
    conn: sqlite3.Connection, token_ids: list[int]
) -> dict[int, list[KalimahSegment]]:
    if not token_ids:
        return {}
    placeholders = ",".join("?" * len(token_ids))
    rows = conn.execute(
        f"""
        SELECT token_id, surface, pos
        FROM quran_token_kalimah
        WHERE token_id IN ({placeholders})
        ORDER BY token_id, kalimah_seq
        """,
        token_ids,
    ).fetchall()
    out: dict[int, list[KalimahSegment]] = defaultdict(list)
    for r in rows:
        tid = int(r["token_id"])
        pos = r["pos"]
        out[tid].append(
            KalimahSegment(surface=str(r["surface"]), pos=str(pos) if pos else None)
        )
    return {k: v for k, v in out.items()}


def max_ayah_in_surah(conn: sqlite3.Connection, surah_no: int) -> int:
    row = conn.execute(
        "SELECT MAX(ayah_no) FROM quran_tokens WHERE surah_no = ?",
        (surah_no,),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def fetch_verse_word_hierarchy(conn: sqlite3.Connection, surah_no: int, ayah_no: int) -> list[VerseWordNode]:
    """
    For each word in the verse: token text, primary root (override or analysis), and lexicon entries (heading + definition).
    """
    rows = conn.execute(
        """
        SELECT
            qt.id,
            qt.word_no,
            qt.token_uthmani,
            ov.root_id AS override_root_id,
            tra.root_id AS analysis_root_id
        FROM quran_tokens qt
        LEFT JOIN token_root_overrides ov ON ov.token_id = qt.id
        LEFT JOIN token_root_analysis tra
            ON tra.token_id = qt.id AND tra.is_primary = 1
        WHERE qt.surah_no = ? AND qt.ayah_no = ?
        ORDER BY qt.word_no
        """,
        (surah_no, ayah_no),
    ).fetchall()

    tids = [int(r["id"]) for r in rows]
    kalimap = _load_kalimat_batch(conn, tids)

    out: list[VerseWordNode] = []
    for row in rows:
        tid = int(row["id"])
        wno = int(row["word_no"])
        uth = str(row["token_uthmani"])
        rid_override = row["override_root_id"]
        rid_analysis = row["analysis_root_id"]
        root_id: int | None
        if rid_override is not None:
            root_id = int(rid_override)
        elif rid_analysis is not None:
            root_id = int(rid_analysis)
        else:
            root_id = None

        root_word: str | None = None
        headings: list[LexiconHeading] = []
        if root_id is not None:
            rw = conn.execute(
                "SELECT root_word FROM lexicon_roots WHERE id = ?",
                (root_id,),
            ).fetchone()
            if rw:
                root_word = str(rw[0])
            he = conn.execute(
                """
                SELECT seq,
                       COALESCE(NULLIF(TRIM(heading_normalized), ''), heading_raw) AS lbl,
                       definition
                FROM lexicon_entries
                WHERE root_id = ?
                ORDER BY seq
                """,
                (root_id,),
            ).fetchall()
            headings = [
                LexiconHeading(
                    seq=int(h["seq"]),
                    label=str(h["lbl"]),
                    definition=str(h["definition"]),
                )
                for h in he
            ]

        kali = kalimap.get(tid)
        out.append(
            VerseWordNode(
                token_id=tid,
                word_no=wno,
                token_uthmani=uth,
                root_word=root_word,
                root_id=root_id,
                entry_headings=tuple(headings),
                kalimat=tuple(kali) if kali else (),
            )
        )
    return out


def _word_morpheme_roots_from_qt_qk_rows(rows: Sequence[sqlite3.Row]) -> list[WordMorphemeRoots]:
    """Group joined ``quran_tokens`` × ``quran_token_kalimah`` rows into words."""
    out: list[WordMorphemeRoots] = []
    cur_word_no: int | None = None
    cur_token = ""
    segs: list[MorphemeRootRow] = []

    def flush() -> None:
        nonlocal cur_word_no, cur_token, segs
        if cur_word_no is None:
            return
        out.append(
            WordMorphemeRoots(
                word_no=cur_word_no,
                token_uthmani=cur_token,
                morphemes=tuple(segs),
            )
        )
        segs = []

    for r in rows:
        wn = int(r["word_no"])
        tok = str(r["token_uthmani"] or "")
        seq = r["kalimah_seq"]
        if cur_word_no is not None and wn != cur_word_no:
            flush()
        cur_word_no = wn
        cur_token = tok
        if seq is not None:
            mt = r["morph_tags"]
            rbw = root_buckwalter_from_morph_tags(mt)
            rar = buckwalter_root_to_arabic(rbw)
            segs.append(
                MorphemeRootRow(
                    kalimah_seq=int(seq),
                    surface=str(r["surface"] or ""),
                    pos=str(r["pos"]) if r["pos"] else None,
                    root_buckwalter=rbw,
                    root_arabic=rar,
                )
            )
    flush()
    return out


def fetch_ayah_morpheme_roots(
    conn: sqlite3.Connection, surah_no: int, ayah_no: int
) -> list[WordMorphemeRoots]:
    """
    Per word in the ayah: ordered morpheme segments with ``ROOT:`` extracted from ``morph_tags``.
    Words without kalimah rows appear with an empty ``morphemes`` tuple.
    """
    rows = conn.execute(
        """
        SELECT
            qt.word_no AS word_no,
            qt.token_uthmani AS token_uthmani,
            qk.kalimah_seq AS kalimah_seq,
            qk.surface AS surface,
            qk.pos AS pos,
            qk.morph_tags AS morph_tags
        FROM quran_tokens qt
        LEFT JOIN quran_token_kalimah qk ON qk.token_id = qt.id
        WHERE qt.surah_no = ? AND qt.ayah_no = ?
        ORDER BY qt.word_no, qk.kalimah_seq
        """,
        (surah_no, ayah_no),
    ).fetchall()
    return _word_morpheme_roots_from_qt_qk_rows(rows)


def fetch_lane_lexicon_for_morph_root(
    conn: sqlite3.Connection,
    *,
    root_arabic: str | None,
    root_buckwalter: str | None,
) -> tuple[LexiconHeading, ...]:
    """
    Match morphology ``ROOT:`` (Arabic or Buckwalter) to ``lexicon_roots`` / ``lexicon_entries``
    (Lane JSON import) via ``root_word_normalized``.
    """
    ar = (root_arabic or "").strip()
    if not ar and root_buckwalter:
        ar = (buckwalter_root_to_arabic(root_buckwalter) or "").strip()
    if not ar:
        return ()
    rw_norm = normalize_arabic(ar)
    if not rw_norm:
        return ()
    row = conn.execute(
        "SELECT id FROM lexicon_roots WHERE root_word_normalized = ?",
        (rw_norm,),
    ).fetchone()
    if not row:
        return ()
    root_id = int(row[0])
    he = conn.execute(
        """
        SELECT seq,
               COALESCE(NULLIF(TRIM(heading_normalized), ''), heading_raw) AS lbl,
               definition
        FROM lexicon_entries
        WHERE root_id = ?
        ORDER BY seq
        """,
        (root_id,),
    ).fetchall()
    return tuple(
        LexiconHeading(
            seq=int(h["seq"]),
            label=str(h["lbl"]),
            definition=str(h["definition"]),
        )
        for h in he
    )


def fetch_morpheme_roots_for_token_ids(
    conn: sqlite3.Connection, token_ids: list[int]
) -> list[WordMorphemeRoots]:
    """
    Same as :func:`fetch_ayah_morpheme_roots` but restricted to the given ``quran_tokens.id`` list
    (e.g. from ``find_match_word_rows``), ordered by ``word_no``.
    """
    if not token_ids:
        return []
    ph = ",".join("?" * len(token_ids))
    rows = conn.execute(
        f"""
        SELECT
            qt.word_no AS word_no,
            qt.token_uthmani AS token_uthmani,
            qk.kalimah_seq AS kalimah_seq,
            qk.surface AS surface,
            qk.pos AS pos,
            qk.morph_tags AS morph_tags
        FROM quran_tokens qt
        LEFT JOIN quran_token_kalimah qk ON qk.token_id = qt.id
        WHERE qt.id IN ({ph})
        ORDER BY qt.word_no ASC, qk.kalimah_seq ASC
        """,
        token_ids,
    ).fetchall()
    return _word_morpheme_roots_from_qt_qk_rows(rows)
