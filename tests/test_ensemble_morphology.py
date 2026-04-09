"""Unit tests for ensemble morphology (no CAMeL / Stanza / OpenAI required)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.morphology_pipeline.camel_candidates import (
    mechanical_morph_segments,
)
from src.morphology_pipeline.llm_rerank import rerank_with_openai
from src.morphology_pipeline.scorer import (
    EnsembleConfig,
    camel_coarse_family,
    confidence_from_margin,
    decision_band,
    rank_scored_candidates,
    score_candidate,
)
from src.morphology_pipeline.camel_candidates import CamelCandidate
from src.morphology_pipeline.stanza_validate import StanzaTokenObservation


def test_mechanical_morph_segments_split() -> None:
    pytest.importorskip("camel_tools")
    # CAMeL bwtok uses underscore-separated morphemes (Buckwalter-ish).
    analysis = {"bwtok": "wa_ktAb"}
    segs = mechanical_morph_segments(
        analysis,
        "bwtok",
        "fallback",
        split_morphs=True,
        diac=False,
    )
    assert len(segs) >= 1


def test_camel_coarse_family() -> None:
    assert camel_coarse_family("noun") == "nominal"
    assert camel_coarse_family(None) is None


def test_score_candidate_ranking() -> None:
    cfg = EnsembleConfig()
    c1 = CamelCandidate(
        rank=0,
        mle_score=0.9,
        pos_lex_logprob=None,
        lex_logprob=None,
        analysis_raw={},
        analysis_export={"pos": "noun", "lex": "kitAb"},
        segments=["كتاب"],
        top_diac=None,
    )
    c2 = CamelCandidate(
        rank=1,
        mle_score=0.4,
        pos_lex_logprob=None,
        lex_logprob=None,
        analysis_raw={},
        analysis_export={"pos": "verb", "lex": "other"},
        segments=["x"],
        top_diac=None,
    )
    obs = StanzaTokenObservation(
        token_index=0,
        surface="كتاب",
        upos="NOUN",
        lemma="kitAb",
        aligned=True,
    )
    s1 = score_candidate(
        c1,
        stanza_obs=obs,
        prev_obs=None,
        next_obs=None,
        cfg=cfg,
    )
    s2 = score_candidate(
        c2,
        stanza_obs=obs,
        prev_obs=None,
        next_obs=None,
        cfg=cfg,
    )
    ranked = rank_scored_candidates([s2, s1])
    assert ranked[0].candidate.rank == 0
    conf, margin = confidence_from_margin(ranked)
    assert conf > 0
    assert margin is not None
    assert decision_band(conf, margin, cfg) in ("high", "medium", "low", "very_low")


def test_rerank_with_openai_mock() -> None:
    payload = {
        "token": "x",
        "context": ["a", "x", "b"],
        "target_index_in_context": 1,
        "candidates": [["a", "b"], ["ab"]],
        "features": [],
    }
    fake_comp = type(
        "C",
        (),
        {
            "choices": [
                type(
                    "Ch",
                    (),
                    {
                        "message": type(
                            "M", (), {"content": json.dumps({"chosen_index": 0, "reason": "test"})}
                        )(),
                        "finish_reason": "stop",
                    },
                )()
            ]
        },
    )()

    class FakeCompletions:
        def create(self, **kwargs):
            return fake_comp

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
        with patch("openai.OpenAI", return_value=FakeClient()):
            idx, reason, meta = rerank_with_openai(payload, model="gpt-4o-mini")
    assert idx == 0
    assert "test" in reason
    assert meta.get("model")
