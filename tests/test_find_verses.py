"""Tests for Step 3 verse matching (token sequence + single-token substring)."""

from src.db.find_verses import find_matching_ayahs


def test_find_matching_ayahs_exact_sequence():
    m = {(1, 1): ["الله", "يتوفى", "الانفس"]}
    hits = find_matching_ayahs(m, ["يتوفى"])
    assert hits == [(1, 1)]


def test_find_matching_ayahs_single_token_substring():
    """نفس as query should match ayah whose token is الانفس (39:42 style)."""
    m = {(39, 42): ["الله", "يتوفى", "الانفس", "حين"]}
    hits = find_matching_ayahs(m, ["نفس"])
    assert (39, 42) in hits


def test_find_matching_ayahs_multi_word_no_substring_trick():
    """Multi-word queries still require full contiguous token equality."""
    m = {(1, 1): ["الله", "نفس", "الاماره"]}
    hits = find_matching_ayahs(m, ["نفس", "الاماره"])
    assert hits == [(1, 1)]
    # "نفس" alone inside one token and "الاماره" next — not how substring works for multi-word
    m2 = {(2, 2): ["ان", "النفس", "للاماره"]}
    hits2 = find_matching_ayahs(m2, ["نفس", "الاماره"])
    assert hits2 == []
