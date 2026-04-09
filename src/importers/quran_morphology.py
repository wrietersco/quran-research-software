"""Import per-word morphological kalimāt from tab-separated Quran morphology files.

Supported format (one segment per line), UTF-8::

    sura:ayah:word:segment<TAB>surface<TAB>POS<TAB>tags

The location field may be wrapped in parentheses as in the Quranic Arabic Corpus::

    (1:1:1:1)<TAB>...

Example sources (same layout after preprocessing):

- `quran-morphology.txt` from https://github.com/mustafa0x/quran-morphology
- `quranic-corpus-morphology-0.4.txt` from https://corpus.quran.com/download/
  (Buckwalter surface; convert to Arabic if needed before import).

``word`` indices must match ``word_no`` in ``quran_tokens`` (Tanzil / Quran.com style).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..db.repositories import delete_all_quran_token_kalimah, insert_quran_token_kalimah
from .morphology_surface import maybe_buckwalter_to_arabic, should_convert_buckwalter

_LOC_RE = re.compile(r"^(\d+):(\d+):(\d+):(\d+)$")


@dataclass(frozen=True)
class MorphologyImportStats:
    lines_parsed: int
    segments_written: int
    tokens_matched: int
    tokens_missing: int
    buckwalter_converted: int = 0


def _parse_location(loc: str) -> tuple[int, int, int, int] | None:
    loc = loc.strip()
    m = _LOC_RE.match(loc)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def import_quran_morphology_txt(
    conn,
    path: Path,
    *,
    clear_existing: bool = True,
    source_label: str = "quran_morphology",
    buckwalter: str = "auto",
) -> MorphologyImportStats:
    """
    Read morphology lines and fill ``quran_token_kalimah`` for matching ``quran_tokens`` rows.

    ``buckwalter``: ``auto`` (detect Quranic-corpus ASCII forms), ``yes``, or ``no``.
    When enabled, segment surfaces are converted with ``pyarabic.trans.tim2utf8``.
    """
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("\ufeff"):
        raw = raw[1:]

    # (surah, ayah, word) -> list of (segment_no, surface, pos, morph_tags)
    buckets: dict[tuple[int, int, int], list[tuple[int, str, str | None, str | None]]] = (
        defaultdict(list)
    )
    lines_parsed = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        loc_raw = parts[0].strip()
        if loc_raw.startswith("(") and loc_raw.endswith(")"):
            loc_raw = loc_raw[1:-1].strip()
        loc_t = _parse_location(loc_raw)
        if loc_t is None:
            continue
        sura, aya, word, seg = loc_t
        surface = parts[1].strip()
        if not surface:
            continue
        pos = parts[2].strip() or None
        morph_tags = parts[3].strip() or None
        buckets[(sura, aya, word)].append((seg, surface, pos, morph_tags))
        lines_parsed += 1

    all_surfaces: list[str] = []
    for _key, items in buckets.items():
        for _seg, surf, _p, _t in items:
            all_surfaces.append(surf)
    bw_mode: Literal["auto", "yes", "no"] = (
        buckwalter if buckwalter in ("auto", "yes", "no") else "auto"
    )
    do_bw = should_convert_buckwalter(all_surfaces, mode=bw_mode)
    bw_count = 0

    token_id_cache: dict[tuple[int, int, int], int | None] = {}

    def token_id_for(sura: int, aya: int, word: int) -> int | None:
        key = (sura, aya, word)
        if key not in token_id_cache:
            row = conn.execute(
                "SELECT id FROM quran_tokens WHERE surah_no = ? AND ayah_no = ? AND word_no = ?",
                key,
            ).fetchone()
            token_id_cache[key] = int(row["id"]) if row else None
        return token_id_cache[key]

    if clear_existing:
        delete_all_quran_token_kalimah(conn)

    segments_written = 0
    tokens_matched = 0
    tokens_missing = 0

    for (sura, aya, word), items in sorted(buckets.items()):
        tid = token_id_for(sura, aya, word)
        if tid is None:
            tokens_missing += 1
            continue
        tokens_matched += 1
        items_sorted = sorted(items, key=lambda x: x[0])
        for seq, (_seg, surface, pos, morph_tags) in enumerate(items_sorted, start=1):
            ar_surf, did = maybe_buckwalter_to_arabic(surface, convert=do_bw)
            if did:
                bw_count += 1
            insert_quran_token_kalimah(
                conn, tid, seq, ar_surf, pos, morph_tags, source_label
            )
            segments_written += 1

    return MorphologyImportStats(
        lines_parsed=lines_parsed,
        segments_written=segments_written,
        tokens_matched=tokens_matched,
        tokens_missing=tokens_missing,
        buckwalter_converted=bw_count,
    )
