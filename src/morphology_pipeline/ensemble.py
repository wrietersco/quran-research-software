"""
Ensemble morphology pipeline: CAMeL top-N → scorer → optional LLM rerank → verse sequence pass.
"""

from __future__ import annotations

import logging
from typing import Any

from .camel_candidates import CamelCandidate, build_word_candidates
from .camel_engine import CamelEngine
from .llm_rerank import build_rerank_payload, rerank_with_openai
from .preprocess import TokenSlice, normalize_for_pipeline, preprocess_text
from .scorer import (
    EnsembleConfig,
    confidence_from_margin,
    decision_band,
    rank_scored_candidates,
    score_candidate,
)
from .segment_builder import build_segments
from .sequence_decode import sequence_consistency_pass
from .stanza_validate import (
    StanzaSentenceResult,
    observation_to_legacy_validator_dict,
    parse_sentence_stanza,
)
from .rules import apply_rules

logger = logging.getLogger(__name__)


def _token_slices_from_input(
    text_or_tokens: str | list[str],
    *,
    strip_diacritics_for_normalized: bool = True,
) -> tuple[list[TokenSlice], str]:
    """Return slices + original string used for Stanza."""
    if isinstance(text_or_tokens, str):
        slices = preprocess_text(
            text_or_tokens,
            strip_diacritics_for_normalized=strip_diacritics_for_normalized,
        )
        return slices, text_or_tokens.strip()
    slices = []
    for i, surf in enumerate(text_or_tokens, start=1):
        norm = normalize_for_pipeline(
            surf,
            strip_diacritics=strip_diacritics_for_normalized,
        )
        slices.append(TokenSlice(token_id=i, surface=surf.strip(), normalized=norm))
    joined = " ".join(t.surface for t in slices)
    return slices, joined


def _camel_block_ensemble(
    engine: CamelEngine,
    cands: list[CamelCandidate],
    chosen: CamelCandidate,
) -> dict[str, Any]:
    return {
        "model": engine.model_name,
        "morph_scheme": engine.morph_scheme,
        "n_candidates": len(cands),
        "chosen_rank": chosen.rank,
        "disambig_score": chosen.mle_score,
        "pos_lex_logprob": chosen.pos_lex_logprob,
        "lex_logprob": chosen.lex_logprob,
        "analysis": chosen.analysis_export,
        "analysis_full": chosen.analysis_raw,
    }


def _process_one_token(
    *,
    engine: CamelEngine,
    cfg: EnsembleConfig,
    sl: TokenSlice,
    stanza_res: StanzaSentenceResult,
    all_slices: list[TokenSlice],
    enable_llm: bool,
    include_full_camel: bool,
) -> dict[str, Any]:
    i = sl.token_id - 1
    prev_obs = stanza_res.observations[i - 1] if i > 0 else None
    curr_obs = stanza_res.observations[i] if i < len(stanza_res.observations) else None
    next_obs = (
        stanza_res.observations[i + 1] if i + 1 < len(stanza_res.observations) else None
    )

    cands = build_word_candidates(engine, sl.surface)
    scored = [
        score_candidate(
            c,
            stanza_obs=curr_obs,
            prev_obs=prev_obs,
            next_obs=next_obs,
            cfg=cfg,
        )
        for c in cands
    ]
    ranked = rank_scored_candidates(scored)
    conf, margin = confidence_from_margin(ranked)
    band = decision_band(conf, margin, cfg)

    stanza_disagree = False
    if ranked and curr_obs and curr_obs.aligned:
        stanza_disagree = ranked[0].parts.get("pos_agree", 1.0) == 0.0

    need_llm = enable_llm and (
        conf < cfg.llm_trigger_below
        or (margin is not None and margin < cfg.near_tie_delta and len(ranked) > 1)
        or stanza_disagree
    )

    chosen = ranked[0].candidate if ranked else (cands[0] if cands else None)
    source = "camel+stanza"
    llm_block: dict[str, Any] | None = None
    chosen_index = 0

    if chosen is None:
        return {
            "token_id": sl.token_id,
            "surface": sl.surface,
            "normalized": sl.normalized,
            "lemma": None,
            "pos": None,
            "segments": [],
            "segments_annotated": [],
            "source": "empty",
            "confidence": 0.0,
            "decision_band": "very_low",
            "margin": None,
            "camel": {},
            "validator": observation_to_legacy_validator_dict(curr_obs),
            "candidates_top": [],
            "llm": None,
            "scoring": {},
            "rules_applied": [],
        }

    if need_llm and len(cands) > 1:
        ctx_list = [s.surface for s in all_slices]
        cand_segs = [c.segments for c in cands]
        feats = [c.analysis_export for c in cands]
        payload = build_rerank_payload(
            sl.surface,
            ctx_list,
            sl.token_id - 1,
            cand_segs,
            feats,
        )
        idx, reason, meta = rerank_with_openai(payload)
        if idx is not None and 0 <= idx < len(cands):
            chosen = cands[idx]
            chosen_index = idx
            source = "camel+llm_rerank"
            llm_block = {"chosen_index": idx, "reason": reason, "meta": meta}
            logger.info("ensemble: LLM selected candidate index=%s", idx)
        else:
            llm_block = {"error": reason, "meta": meta}
            logger.warning("ensemble: LLM rerank failed, keeping scored best")
    elif need_llm and len(cands) <= 1:
        logger.info("ensemble: LLM skipped (single candidate)")

    if band == "very_low":
        source = "camel_uncertain" if source == "camel+stanza" else source

    seg_strings = list(chosen.segments)
    seg_objs = build_segments(seg_strings, chosen.analysis_export)
    lemma = chosen.analysis_export.get("lex")
    lemma = str(lemma) if lemma is not None else None
    pos = chosen.analysis_export.get("pos")
    pos = str(pos) if pos is not None else None

    camel_block = _camel_block_ensemble(engine, cands, chosen)
    if not include_full_camel:
        camel_block.pop("analysis_full", None)

    validator_out = observation_to_legacy_validator_dict(
        curr_obs, camel_pos=pos, camel_lex=lemma
    )

    top_k = min(cfg.very_low_report_top_k, len(cands))
    candidates_summary = [
        {
            "rank": c.rank,
            "segments": c.segments,
            "mle_score": c.mle_score,
            "analysis": c.analysis_export,
        }
        for c in cands[:top_k]
    ]

    record: dict[str, Any] = {
        "token_id": sl.token_id,
        "surface": sl.surface,
        "normalized": sl.normalized,
        "lemma": lemma,
        "pos": pos,
        "segments": seg_strings,
        "segments_annotated": seg_objs,
        "source": source,
        "confidence": round(conf, 4),
        "decision_band": band,
        "margin": None if margin is None else round(margin, 4),
        "chosen_candidate_rank": chosen.rank,
        "chosen_index_after_llm": (
            llm_block.get("chosen_index")
            if llm_block and "chosen_index" in llm_block
            else None
        ),
        "scoring": {
            "top_total": round(ranked[0].total_score, 4) if ranked else None,
            "top_parts": ranked[0].parts if ranked else {},
            "runner_up_total": round(ranked[1].total_score, 4) if len(ranked) > 1 else None,
        },
        "camel": camel_block,
        "validator": validator_out,
        "candidates_top": candidates_summary,
        "llm": llm_block,
        "stanza_disagreement": stanza_disagree,
        "rules_applied": [],
    }
    if band == "very_low":
        record["uncertainty"] = True
    apply_rules(record)
    return record


class EnsembleMorphologyPipeline:
    def __init__(
        self,
        *,
        cfg: EnsembleConfig | None = None,
        camel_model: str = "calima-msa-r13",
        morph_scheme: str = "bwtok",
        split_morphs: bool = True,
        diac: bool = False,
        strip_diacritics_for_normalized: bool = True,
        use_stanza: bool = True,
        enable_llm: bool = False,
    ) -> None:
        self.cfg = cfg or EnsembleConfig()
        self.enable_llm = enable_llm
        self.strip_diac = strip_diacritics_for_normalized
        self.use_stanza = use_stanza
        logger.info(
            "EnsembleMorphologyPipeline: camel_top=%s stanza=%s llm=%s",
            self.cfg.camel_top,
            use_stanza,
            enable_llm,
        )
        self._engine = CamelEngine(
            model_name=camel_model,
            morph_scheme=morph_scheme,
            split_morphs=split_morphs,
            diac=diac,
            top=self.cfg.camel_top,
        )

    def process_sentence(
        self,
        text_or_tokens: str | list[str],
        *,
        original_text: str | None = None,
        include_full_camel: bool = False,
    ) -> dict[str, Any]:
        slices, joined = _token_slices_from_input(
            text_or_tokens, strip_diacritics_for_normalized=self.strip_diac
        )
        text_for_stanza = (original_text or joined).strip()
        tokens = [s.surface for s in slices]
        logger.info(
            "process_sentence: %s tokens, stanza_text_len=%s",
            len(tokens),
            len(text_for_stanza),
        )

        if self.use_stanza:
            stanza_res = parse_sentence_stanza(tokens, original_text=text_for_stanza)
        else:
            stanza_res = StanzaSentenceResult(
                ran=False, skipped_reason="stanza_disabled_by_config"
            )

        if stanza_res.ran and len(stanza_res.observations) != len(slices):
            logger.warning(
                "process_sentence: stanza obs count %s != tokens %s",
                len(stanza_res.observations),
                len(slices),
            )

        records: list[dict[str, Any]] = []
        ambiguous_ids: list[int] = []
        for sl in slices:
            rec = _process_one_token(
                engine=self._engine,
                cfg=self.cfg,
                sl=sl,
                stanza_res=stanza_res,
                all_slices=slices,
                enable_llm=self.enable_llm,
                include_full_camel=include_full_camel,
            )
            records.append(rec)
            if rec.get("uncertainty") or rec.get("decision_band") == "low":
                ambiguous_ids.append(sl.token_id)

        seq_flags = sequence_consistency_pass(
            records, ambiguous_token_ids=ambiguous_ids
        )
        out = {
            "tokens": records,
            "sequence": seq_flags,
            "stanza_ran": stanza_res.ran,
            "stanza_skipped_reason": stanza_res.skipped_reason,
        }
        logger.info("process_sentence: completed %s token record(s)", len(records))
        return out


def process_sentence_ensemble(
    text_or_tokens: str | list[str],
    *,
    enable_llm: bool = False,
    cfg: EnsembleConfig | None = None,
    include_full_camel: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """One-shot ensemble run."""
    pipe = EnsembleMorphologyPipeline(
        cfg=cfg, enable_llm=enable_llm, **kwargs
    )
    return pipe.process_sentence(
        text_or_tokens, include_full_camel=include_full_camel
    )
