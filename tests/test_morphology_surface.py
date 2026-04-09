"""Tests for Quranic morphology surface normalization (Buckwalter vs Arabic)."""

from __future__ import annotations

from src.importers.morphology_surface import (
    infer_buckwalter_for_file,
    looks_like_buckwalter_form,
    maybe_buckwalter_to_arabic,
    should_convert_buckwalter,
    surface_has_arabic,
)


def test_arabic_example_file_not_buckwalter() -> None:
    sample = ["بِ", "سْمِ", "ٱللَّهِ"]
    assert not infer_buckwalter_for_file(sample)
    assert not should_convert_buckwalter(sample, mode="auto")


def test_buckwalter_sample_detected() -> None:
    # infer_buckwalter_for_file needs >= 8 nonempty samples
    sample = [
        "bi",
        "som",
        "Al~ahi",
        "Alr~aHomaAni",
        "wa",
        "Einda",
        "All~ahi",
        "fiy",
        "Als~amA'i",
    ]
    assert infer_buckwalter_for_file(sample)
    assert should_convert_buckwalter(sample, mode="auto")


def test_maybe_convert_bi() -> None:
    out, did = maybe_buckwalter_to_arabic("bi", convert=True)
    assert did
    assert "\u0628" in out


def test_arabic_passthrough_when_converting() -> None:
    s = "بِ"
    out, did = maybe_buckwalter_to_arabic(s, convert=True)
    assert not did
    assert out == s


def test_looks_like_buckwalter() -> None:
    assert looks_like_buckwalter_form("Alr~aHomaAni")
    assert not looks_like_buckwalter_form("بِ")
    assert surface_has_arabic("ٱلرَّحْمَٰنِ")
