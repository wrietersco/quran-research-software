"""Unicode / orthography normalization for morphology pipeline (Service A, part 1)."""

from __future__ import annotations

import logging
import re
import unicodedata

from src.normalize.arabic import normalize_arabic

logger = logging.getLogger(__name__)


def normalize_for_pipeline(
    surface: str,
    *,
    strip_diacritics: bool = True,
    unify_alif: bool = True,
    unify_ta_marbuta: bool = False,
) -> str:
    """
    Normalization that helps analyzers (optional diacritic stripping).

    When ``strip_diacritics`` is False, only NFKC + tatweel cleanup is applied so
    vocalized Quran tokens stay intact for display while a light normalized copy exists.
    """
    if not surface:
        return ""
    s = unicodedata.normalize("NFKC", surface)
    s = s.replace("\u0640", "")  # tatweel
    if strip_diacritics:
        out = normalize_arabic(
            s, unify_alif=unify_alif, unify_ta_marbuta=unify_ta_marbuta
        )
        logger.debug(
            "normalize_for_pipeline: strip_diacritics=True in_len=%s out_len=%s",
            len(surface),
            len(out),
        )
        return out
    if unify_alif:
        for a, b in (
            ("\u0622", "\u0627"),
            ("\u0623", "\u0627"),
            ("\u0625", "\u0627"),
            ("\u0671", "\u0627"),
        ):
            s = s.replace(a, b)
    if unify_ta_marbuta:
        s = s.replace("\u0629", "\u0647")
    s = re.sub(r"\s+", " ", s).strip()
    logger.debug(
        "normalize_for_pipeline: preserved diacritics in_len=%s out_len=%s",
        len(surface),
        len(s),
    )
    return s
