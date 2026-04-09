"""
Orchestrates Services A–F: preprocess → CAMeL → segments → confidence → Stanza → rules → record.
"""

from __future__ import annotations

import logging
from typing import Any

from .camel_engine import CamelDisambiguatedToken, CamelEngine
from .exporter import token_record_to_dict
from .preprocess import preprocess_single_surface
from .rules import apply_rules
from .segment_builder import build_segments
from .validator import StanzaValidationResult, run_stanza_on_token, validation_to_dict

logger = logging.getLogger(__name__)


def _confidence_score(
    camel: CamelDisambiguatedToken,
    stanza: StanzaValidationResult,
) -> float:
    """Blend CAMeL disambiguation score with Stanza coarse POS agreement."""
    base = 0.55
    if camel.disambig_score is not None:
        base = float(camel.disambig_score)
    logger.debug("_confidence_score: camel_base=%s", base)
    if not stanza.ran:
        logger.debug("_confidence_score: stanza did not run -> base only")
        return max(0.0, min(1.0, base))
    if stanza.skipped_reason and stanza.stanza_upos is None:
        logger.debug(
            "_confidence_score: stanza incomplete (%s) -> small penalty",
            stanza.skipped_reason,
        )
        return max(0.0, min(1.0, base - 0.05))
    if stanza.agreement_coarse is True:
        adj = min(1.0, base + 0.05)
        logger.info("_confidence_score: stanza AGREES coarse POS -> %s", adj)
        return adj
    if stanza.agreement_coarse is False:
        adj = max(0.0, base - 0.2)
        logger.warning("_confidence_score: stanza DISAGREES coarse POS -> %s", adj)
        return adj
    return max(0.0, min(1.0, base))


class MorphologyPipeline:
    """Full pipeline with shared CAMeL engine instance."""

    def __init__(
        self,
        *,
        camel_model: str = "calima-msa-r13",
        morph_scheme: str = "bwtok",
        split_morphs: bool = True,
        diac: bool = False,
        strip_diacritics_for_normalized: bool = True,
        use_stanza: bool = True,
    ) -> None:
        logger.info(
            "MorphologyPipeline: init camel_model=%s scheme=%s stanza=%s",
            camel_model,
            morph_scheme,
            use_stanza,
        )
        self._engine = CamelEngine(
            model_name=camel_model,
            morph_scheme=morph_scheme,
            split_morphs=split_morphs,
            diac=diac,
        )
        self._strip_diac = strip_diacritics_for_normalized
        self._use_stanza = use_stanza

    def process_token(
        self,
        surface: str,
        *,
        token_id: int = 1,
        context_sentence: str | None = None,
        include_full_camel_analysis: bool = False,
    ) -> dict[str, Any]:
        """
        Run full stack for one surface string.

        ``context_sentence`` should contain the token for better Stanza alignment; defaults to token only.
        """
        logger.info(
            "process_token: START token_id=%s surface=%r context_len=%s",
            token_id,
            surface,
            len(context_sentence or ""),
        )
        ts = preprocess_single_surface(
            surface, token_id=token_id, strip_diacritics_for_normalized=self._strip_diac
        )
        camel = self._engine.analyze_token(ts.surface)
        segments = build_segments(camel.morph_segments, camel.analysis_export)
        lemma = camel.analysis_export.get("lex")
        if lemma is not None:
            lemma = str(lemma)
        pos = camel.analysis_export.get("pos")
        if pos is not None:
            pos = str(pos)

        stanza = StanzaValidationResult(
            ran=False, skipped_reason="stanza_disabled_by_config"
        )
        if self._use_stanza:
            ctx = context_sentence if context_sentence else ts.surface
            stanza = run_stanza_on_token(
                ts.surface,
                context_sentence=ctx,
                camel_pos=pos,
                camel_lex=lemma,
            )
        conf = _confidence_score(camel, stanza)

        camel_block: dict[str, Any] = {
            "model": camel.model_name,
            "morph_scheme": camel.morph_scheme,
            "disambig_score": camel.disambig_score,
            "pos_lex_logprob": camel.pos_lex_logprob,
            "lex_logprob": camel.lex_logprob,
            "n_analyses": camel.n_analyses,
            "top_diac": camel.top_analysis_diac,
            "analysis": camel.analysis_export,
            "morph_segments_raw": list(camel.morph_segments),
        }
        if include_full_camel_analysis:
            camel_block["analysis_full"] = camel.analysis_raw
            logger.debug("process_token: attached analysis_full keys=%s", len(camel.analysis_raw))

        validator_out = validation_to_dict(stanza)

        record = token_record_to_dict(
            token_id=ts.token_id,
            surface=ts.surface,
            normalized=ts.normalized,
            lemma=lemma,
            pos=pos,
            segments=segments,
            camel_block=camel_block,
            validator_block=validator_out,
            confidence=conf,
            rules_applied=[],
        )
        apply_rules(record)
        logger.info(
            "process_token: DONE token_id=%s confidence=%s segments=%s",
            token_id,
            conf,
            len(segments),
        )
        return record


def process_single_token(
    surface: str,
    *,
    token_id: int = 1,
    context_sentence: str | None = None,
    include_full_camel_analysis: bool = False,
    use_stanza: bool = True,
    **camel_kw: Any,
) -> dict[str, Any]:
    """One-shot pipeline (creates a new :class:`MorphologyPipeline`)."""
    pipe = MorphologyPipeline(use_stanza=use_stanza, **camel_kw)
    return pipe.process_token(
        surface,
        token_id=token_id,
        context_sentence=context_sentence,
        include_full_camel_analysis=include_full_camel_analysis,
    )
