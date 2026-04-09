"""Unit tests for corpus root extraction from kalimah FEATURES strings."""

from src.db.corpus_roots import extract_corpus_root_buckwalter, root_buckwalter_from_morph_tags


def test_prefers_stem_root_over_prefix():
    stem = "STEM|POS:N|LEM:som|ROOT:smw|M|GEN"
    prefix = "PREF|ROOT:xy|..."
    assert extract_corpus_root_buckwalter([prefix, stem]) == "smw"


def test_first_root_when_no_stem_marker():
    assert extract_corpus_root_buckwalter(["POS:V|ROOT:ktb|..."]) == "ktb"


def test_empty_returns_none():
    assert extract_corpus_root_buckwalter([]) is None
    assert extract_corpus_root_buckwalter([None, ""]) is None


def test_root_buckwalter_from_single_segment_tags():
    assert root_buckwalter_from_morph_tags("STEM|POS:N|ROOT:smw|M") == "smw"
    assert root_buckwalter_from_morph_tags(None) is None
    assert root_buckwalter_from_morph_tags("POS:P|no root here") is None
