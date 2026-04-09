"""Unit tests for morphology_pipeline (no CAMeL / Stanza required)."""

from __future__ import annotations

from src.morphology_pipeline.segment_builder import build_segments, build_role_slots


def test_build_role_slots_order() -> None:
    analysis = {
        "prc1": "wa_conj",
        "stem": "x",
        "enc0": "3mp_pron",
    }
    slots = build_role_slots(analysis)
    keys = [s[0] for s in slots]
    assert keys == ["prc1", "stem", "enc0"]


def test_build_segments_aligned() -> None:
    analysis = {"prc1": "wa_conj", "stem": "stemtag", "enc0": "3mp_pron"}
    forms = ["وَ", "كلمة", "هم"]
    segs = build_segments(forms, analysis)
    assert len(segs) == 3
    assert segs[0]["role"] == "conjunction"
    assert segs[1]["role"] == "stem"
    assert "enclitic" in segs[2]["role"]


def test_build_segments_fallback() -> None:
    analysis = {"stem": "only"}
    forms = ["a", "b", "c", "d"]
    segs = build_segments(forms, analysis)
    assert len(segs) == 4
    assert any(s.get("note") == "alignment_fallback" for s in segs)
