"""
Service A — glue: TokenSlice + full-line / single-token preprocessing.

Normalization lives in ``normalize.py``; word splitting in ``tokenize.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .normalize import normalize_for_pipeline
from .tokenize import tokenize_orthographic

logger = logging.getLogger(__name__)


@dataclass
class TokenSlice:
    """One orthographic token with indices (1-based token_id)."""

    token_id: int
    surface: str
    normalized: str
    char_start: int | None = None
    char_end: int | None = None
    meta: dict = field(default_factory=dict)


def preprocess_text(
    text: str,
    *,
    strip_diacritics_for_normalized: bool = True,
    unify_alif: bool = True,
    unify_ta_marbuta: bool = False,
) -> list[TokenSlice]:
    """
    Full Service A: tokenize line, assign 1-based ids, attach normalized surface per token.
    """
    logger.info("preprocess_text: input length=%s chars", len(text or ""))
    words = tokenize_orthographic(text)
    out: list[TokenSlice] = []
    pos = 0
    for i, w in enumerate(words, start=1):
        norm = normalize_for_pipeline(
            w,
            strip_diacritics=strip_diacritics_for_normalized,
            unify_alif=unify_alif,
            unify_ta_marbuta=unify_ta_marbuta,
        )
        start = text.find(w, pos) if text else None
        end = start + len(w) if start is not None and start >= 0 else None
        if start is not None and start >= 0:
            pos = end or pos
        slice_ = TokenSlice(
            token_id=i,
            surface=w,
            normalized=norm,
            char_start=start if start is not None and start >= 0 else None,
            char_end=end,
        )
        out.append(slice_)
        logger.debug(
            "preprocess_text: token_id=%s surface=%r normalized=%r span=%s-%s",
            i,
            w,
            norm,
            slice_.char_start,
            slice_.char_end,
        )
    logger.info("preprocess_text: produced %s TokenSlice(s)", len(out))
    return out


def preprocess_single_surface(
    surface: str,
    *,
    token_id: int = 1,
    strip_diacritics_for_normalized: bool = True,
) -> TokenSlice:
    """Convenience: one token (no line tokenization)."""
    norm = normalize_for_pipeline(
        surface,
        strip_diacritics=strip_diacritics_for_normalized,
    )
    ts = TokenSlice(token_id=token_id, surface=surface, normalized=norm)
    logger.info(
        "preprocess_single_surface: token_id=%s surface=%r normalized=%r",
        token_id,
        surface,
        norm,
    )
    return ts
