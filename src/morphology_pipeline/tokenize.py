"""Orthographic word tokenization (Service A, part 2)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def tokenize_orthographic(text: str) -> list[str]:
    """
    Space-separated words; punctuation split from words when CAMeL is available.

    Falls back to whitespace split with a WARNING if ``camel_tools`` is missing.
    """
    text = (text or "").strip()
    if not text:
        logger.info("tokenize_orthographic: empty input -> []")
        return []
    try:
        from camel_tools.tokenizers.word import simple_word_tokenize

        toks = simple_word_tokenize(text)
        logger.info(
            "tokenize_orthographic: camel simple_word_tokenize -> %s token(s): %s",
            len(toks),
            toks[:20],
        )
        return toks
    except ImportError:
        logger.warning(
            "tokenize_orthographic: camel_tools not installed; using whitespace split"
        )
        return [w for w in text.split() if w]
