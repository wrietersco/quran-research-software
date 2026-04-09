"""
Verse-level algorithmic pass: flags, segment-count stats, non-mutating hints (Service 8).
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def sequence_consistency_pass(
    token_records: list[dict[str, Any]],
    *,
    ambiguous_token_ids: list[int] | None = None,
) -> dict[str, Any]:
    """
    Inspect chosen segmentations across a verse.

    Does not modify ``token_records``; returns summary for export / review.
    """
    n = len(token_records)
    seg_lens = [len(r.get("segments") or []) for r in token_records]
    len_hist = Counter(seg_lens)
    logger.info("sequence_consistency_pass: tokens=%s segment_length_hist=%s", n, dict(len_hist))

    by_surface: dict[str, list[tuple[int, tuple[str, ...]]]] = defaultdict(list)
    for r in token_records:
        tid = int(r.get("token_id", 0))
        surf = str(r.get("surface", ""))
        segs = tuple(r.get("segments") or [])
        by_surface[surf].append((tid, segs))

    suggestions: list[dict[str, Any]] = []
    for surf, items in by_surface.items():
        if len(items) < 2 or len({t[1] for t in items}) <= 1:
            continue
        pat_counts = Counter(t[1] for t in items)
        dominant, cnt = pat_counts.most_common(1)[0]
        if cnt >= 2 and cnt / len(items) >= 0.5:
            suggestions.append(
                {
                    "surface": surf,
                    "dominant_pattern": list(dominant),
                    "dominant_count": cnt,
                    "total_occurrences": len(items),
                    "note": "non_mutating_hint_same_surface_mixed_segmentation",
                }
            )
            logger.debug(
                "sequence_consistency_pass: hint surface=%r dominant=%s",
                surf,
                dominant,
            )

    amb_ids = set(ambiguous_token_ids or [])
    flags = {
        "ambiguous_token_ids": sorted(amb_ids),
        "segment_length_histogram": {str(k): v for k, v in len_hist.items()},
        "sequence_suggestions": suggestions,
    }
    logger.info(
        "sequence_consistency_pass: suggestions=%s ambiguous_ids=%s",
        len(suggestions),
        len(amb_ids),
    )
    return flags
