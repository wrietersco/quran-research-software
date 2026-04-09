"""CAMeL pipeline tests (skipped when camel-tools / camel_data not available)."""

from __future__ import annotations

import pytest

pytest.importorskip("camel_tools", reason="camel-tools not installed")


def test_analyze_sentence_smoke() -> None:
    from src.morphology.camel_pipeline import analyze_sentence

    r = analyze_sentence("السلام عليكم", scheme="d3tok", split_morphs=True)
    assert r.tokens
    assert len(r.words) == len(r.tokens)
    assert r.morph_flat
