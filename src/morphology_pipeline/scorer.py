"""
Ensemble scoring: CAMeL rank + Stanza agreement + lemma similarity + light context (Service 6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.normalize.arabic import normalize_arabic

from .camel_candidates import CamelCandidate
from .stanza_validate import StanzaTokenObservation, coarse_pos_families

logger = logging.getLogger(__name__)


@dataclass
class EnsembleConfig:
    camel_top: int = 5
    weight_mle: float = 0.45
    weight_pos_agree: float = 0.25
    weight_lemma: float = 0.2
    weight_context: float = 0.1
    confidence_high: float = 0.82
    confidence_medium: float = 0.55
    margin_epsilon: float = 0.06
    llm_trigger_below: float = 0.58
    near_tie_delta: float = 0.04
    very_low_report_top_k: int = 3


def camel_coarse_family(camel_pos: str | None) -> str | None:
    fam, _ = coarse_pos_families(camel_pos, None)
    return fam


def stanza_coarse_family(upos: str | None) -> str | None:
    _, fam = coarse_pos_families(None, upos)
    return fam


def pos_agreement_score(camel_pos: str | None, stanza_upos: str | None) -> float:
    if not stanza_upos:
        return 0.55
    fam_c, fam_u = coarse_pos_families(camel_pos, stanza_upos)
    if fam_c is None or fam_u is None:
        return 0.55
    return 1.0 if fam_c == fam_u else 0.0


def lemma_similarity_score(camel_lex: str | None, stanza_lemma: str | None) -> float:
    if not camel_lex or not stanza_lemma:
        return 0.5
    a = normalize_arabic(str(camel_lex).strip())
    b = normalize_arabic(str(stanza_lemma).strip())
    if not a or not b:
        return 0.5
    return 1.0 if a == b else 0.0


def context_consistency_score(
    camel_pos: str | None,
    prev_obs: StanzaTokenObservation | None,
    next_obs: StanzaTokenObservation | None,
) -> float:
    """
    Algorithmic: compare camel coarse POS to neighbors' Stanza coarse families.
    Neutral 0.5 if neighbors missing; else average of match scores.
    """
    cf = camel_coarse_family(camel_pos)
    if cf is None:
        return 0.55
    scores: list[float] = []
    for obs in (prev_obs, next_obs):
        if obs is None or not obs.aligned or not obs.upos:
            continue
        nf = stanza_coarse_family(obs.upos)
        if nf is None:
            continue
        scores.append(1.0 if cf == nf else 0.65)
    if not scores:
        return 0.55
    return sum(scores) / len(scores)


@dataclass
class ScoredCandidate:
    candidate: CamelCandidate
    total_score: float
    parts: dict[str, float]


def score_candidate(
    cand: CamelCandidate,
    *,
    stanza_obs: StanzaTokenObservation | None,
    prev_obs: StanzaTokenObservation | None,
    next_obs: StanzaTokenObservation | None,
    cfg: EnsembleConfig,
) -> ScoredCandidate:
    mle = cand.mle_score if cand.mle_score is not None else 0.0
    mle = max(0.0, min(1.0, mle))
    pos = cand.analysis_export.get("pos")
    pos = str(pos) if pos is not None else None
    lex = cand.analysis_export.get("lex")
    lex = str(lex) if lex is not None else None
    st_upos = stanza_obs.upos if stanza_obs and stanza_obs.aligned else None
    st_lemma = stanza_obs.lemma if stanza_obs and stanza_obs.aligned else None

    p_pos = pos_agreement_score(pos, st_upos)
    p_lex = lemma_similarity_score(lex, st_lemma)
    p_ctx = context_consistency_score(pos, prev_obs, next_obs)

    total = (
        cfg.weight_mle * mle
        + cfg.weight_pos_agree * p_pos
        + cfg.weight_lemma * p_lex
        + cfg.weight_context * p_ctx
    )
    parts = {
        "mle": mle,
        "pos_agree": p_pos,
        "lemma": p_lex,
        "context": p_ctx,
    }
    logger.debug(
        "score_candidate: rank=%s total=%.4f parts=%s",
        cand.rank,
        total,
        parts,
    )
    return ScoredCandidate(candidate=cand, total_score=total, parts=parts)


def rank_scored_candidates(scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(scored, key=lambda s: -s.total_score)


def confidence_from_margin(scored_sorted: list[ScoredCandidate]) -> tuple[float, float | None]:
    """Return (confidence, margin) where margin is top1 - top2."""
    if not scored_sorted:
        return 0.0, None
    if len(scored_sorted) == 1:
        return max(0.0, min(1.0, scored_sorted[0].total_score)), None
    t0 = scored_sorted[0].total_score
    t1 = scored_sorted[1].total_score
    margin = t0 - t1
    conf = max(0.0, min(1.0, t0 * (0.5 + 0.5 * min(1.0, margin * 5))))
    return conf, margin


def decision_band(
    confidence: float,
    margin: float | None,
    cfg: EnsembleConfig,
) -> str:
    if confidence >= cfg.confidence_high and (
        margin is None or margin >= cfg.margin_epsilon
    ):
        return "high"
    if confidence >= cfg.confidence_medium:
        if margin is not None and margin < cfg.near_tie_delta:
            return "low"
        return "medium"
    return "very_low"
