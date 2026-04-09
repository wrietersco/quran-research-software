"""
Service C — build labeled segments from CAMeL morph features + tokenizer output.

Uses disambiguated ``prc*``, ``stem``, ``enc*`` slots aligned to ``morph_segments`` when counts match.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

PRC_ORDER = ("prc3", "prc2", "prc1", "prc0")
ENC_ORDER = ("enc0", "enc1", "enc2")


def _is_active_feat(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    return s.lower() not in ("noan", "na", "0", "_")


def _tag_role(slot_name: str, tag: str) -> str:
    """Map CALIMA-style tag string to a coarse role for JSON."""
    t = (tag or "").lower()
    if slot_name.startswith("prc"):
        if "conj" in t or t.startswith("fa") or t.startswith("wa"):
            return "conjunction"
        if "prep" in t or t.startswith("bi") or t.startswith("li") or t.startswith("ka"):
            return "preposition"
        if "det" in t or "al" in t:
            return "determiner"
        return "proclitic"
    if slot_name.startswith("enc"):
        if "pron" in t or "poss" in t or "1s" in t or "2" in t or "3" in t:
            return "enclitic_pronoun"
        return "enclitic"
    if slot_name == "stem":
        if "verb" in t or "pv" in t or "iv" in t:
            return "stem"
        if "noun" in t or "adj" in t:
            return "stem"
        return "stem"
    return "unknown"


def _pos_for_stem(analysis_export: dict[str, Any]) -> str | None:
    p = analysis_export.get("pos")
    return str(p) if p is not None and not _is_active_feat(p) else None


def build_role_slots(analysis_export: dict[str, Any]) -> list[tuple[str, str, str]]:
    """
    Ordered semantic slots: (slot_key, tag_value, coarse_role).

    Order: prc3..prc0, stem, enc0..enc2 — mirrors typical Arabic template.
    """
    slots: list[tuple[str, str, str]] = []
    for k in PRC_ORDER:
        v = analysis_export.get(k)
        if _is_active_feat(v):
            tag = str(v)
            slots.append((k, tag, _tag_role(k, tag)))
            logger.debug("build_role_slots: added %s=%r -> %s", k, v, slots[-1][2])
    st = analysis_export.get("stem")
    if _is_active_feat(st):
        tag = str(st)
        slots.append(("stem", tag, "stem"))
        logger.debug("build_role_slots: stem=%r", tag)
    for k in ENC_ORDER:
        v = analysis_export.get(k)
        if _is_active_feat(v):
            tag = str(v)
            slots.append((k, tag, _tag_role(k, tag)))
            logger.debug("build_role_slots: added %s=%r -> %s", k, v, slots[-1][2])
    logger.info("build_role_slots: total_slots=%s", len(slots))
    return slots


def build_segments(
    morph_segments: list[str],
    analysis_export: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Pair tokenizer surface pieces with roles derived from disambiguated features.

    If slot count != len(morph_segments), emit segments with ``role: morpheme`` fallback
    and log a WARNING (libraries can disagree on clitic count).
    """
    forms = [x for x in morph_segments if x]
    slots = build_role_slots(analysis_export)
    stem_pos = _pos_for_stem(analysis_export)

    if not forms:
        logger.warning("build_segments: no morph segments from tokenizer")
        return []

    out: list[dict[str, Any]] = []
    if len(slots) == len(forms):
        logger.info(
            "build_segments: slot/form alignment OK (%s segments)", len(forms)
        )
        for (slot_key, tag, role), form in zip(slots, forms):
            seg: dict[str, Any] = {
                "form": form,
                "role": role,
                "camel_slot": slot_key,
                "camel_tag": tag,
            }
            if slot_key == "stem" and stem_pos:
                seg["pos"] = stem_pos
            out.append(seg)
        return out

    logger.warning(
        "build_segments: MISMATCH slots=%s forms=%s — using generic morpheme roles",
        len(slots),
        len(forms),
    )
    for i, form in enumerate(forms):
        guess = "morpheme"
        if i == 0 and len(forms) > 1:
            guess = "prefix_or_proclitic"
        if i == len(forms) - 1 and len(forms) > 1:
            guess = "suffix_or_enclitic"
        if len(forms) == 1:
            guess = "whole_token"
        out.append(
            {
                "form": form,
                "role": guess,
                "camel_slot": None,
                "camel_tag": None,
                "note": "alignment_fallback",
            }
        )
    return out
