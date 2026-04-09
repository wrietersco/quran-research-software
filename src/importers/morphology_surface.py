"""Normalize morphology segment surfaces for import (Arabic vs Quranic-corpus Buckwalter)."""

from __future__ import annotations

import re
from typing import Literal

_ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufefc]")

# Buckwalter-style FORM from corpus.quran.com dumps: ASCII letters + TIM punctuation.
_BW_TOKEN_RE = re.compile(r"^[A-Za-z0-9|&><'`~\[\]}{^_#+o%FODNJZ:\-]+$")


def surface_has_arabic(s: str) -> bool:
    return bool(_ARABIC_RE.search(s))


def looks_like_buckwalter_form(s: str) -> bool:
    s = s.strip()
    if not s or surface_has_arabic(s):
        return False
    return bool(_BW_TOKEN_RE.match(s))


def infer_buckwalter_for_file(surfaces: list[str]) -> bool:
    """
    Return True if surfaces look like corpus Buckwalter (mostly ASCII) rather than Arabic script.
    """
    nonempty = [x.strip() for x in surfaces if x.strip()]
    if len(nonempty) < 8:
        return False
    sample = nonempty[: min(400, len(nonempty))]
    n_arabic = sum(1 for s in sample if surface_has_arabic(s))
    n_bw = sum(1 for s in sample if looks_like_buckwalter_form(s))
    if n_arabic >= len(sample) * 0.5:
        return False
    return n_bw >= len(sample) * 0.85


def buckwalter_form_to_arabic(form: str) -> str:
    """Convert a Quranic-corpus style Buckwalter FORM to Arabic Unicode (best effort)."""
    from pyarabic.trans import tim2utf8

    return tim2utf8(form.strip())


def should_convert_buckwalter(
    sample_surfaces: list[str],
    *,
    mode: Literal["auto", "yes", "no"],
) -> bool:
    if mode == "no":
        return False
    if mode == "yes":
        return True
    return infer_buckwalter_for_file(sample_surfaces)


def maybe_buckwalter_to_arabic(surface: str, *, convert: bool) -> tuple[str, bool]:
    """
    If ``convert`` and the token looks like Buckwalter, return Arabic and True.
    Otherwise return the original surface and False.
    """
    t = surface.strip()
    if not convert or not t:
        return surface, False
    if surface_has_arabic(t):
        return surface, False
    if not looks_like_buckwalter_form(t):
        return surface, False
    try:
        return buckwalter_form_to_arabic(t), True
    except Exception:
        return surface, False
