"""
CAMeL top-N segmentation candidates — mechanical extraction from each ScoredAnalysis.

``MorphologicalTokenizer`` only uses rank-0; we read ``analysis[scheme]`` per candidate
and apply the same dediac/split policy as CAMeL (no hand-authored split rules).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .camel_engine import CamelEngine, export_analysis_features

logger = logging.getLogger(__name__)

# Mirrors camel_tools.tokenizers.morphological._DIAC_TYPE (undiacritized output).
_REMOVE_PLUSES = re.compile(r"(_\+|\+_)+")


def _default_dediac(tok: str) -> str:
    from camel_tools.utils.dediac import dediac_ar

    return dediac_ar(tok)


def _bwtok_dediac(tok: str) -> str:
    from camel_tools.utils.dediac import dediac_ar

    return _REMOVE_PLUSES.sub(r"\g<1>", dediac_ar(tok).strip("+_"))


_SCHEME_DEDIAC: dict[str, Any] = {
    "atbtok": _default_dediac,
    "atbseg": _default_dediac,
    "bwtok": _bwtok_dediac,
    "d1tok": _default_dediac,
    "d1seg": _default_dediac,
    "d2tok": _default_dediac,
    "d2seg": _default_dediac,
    "d3tok": _default_dediac,
    "d3seg": _default_dediac,
}


def mechanical_morph_segments(
    analysis: dict[str, Any],
    scheme: str,
    surface_word: str,
    *,
    split_morphs: bool,
    diac: bool,
) -> list[str]:
    """
    Extract segment strings from one CALIMA analysis dict (same logic as MorphologicalTokenizer
    inner loop, but for an arbitrary analysis row).
    """
    tok = analysis.get(scheme)
    if tok is None or tok == "NOAN" or str(tok).strip() == "":
        tok = surface_word
        logger.debug(
            "mechanical_morph_segments: scheme %r missing/NOAN -> whole word", scheme
        )
    s = str(tok)
    if not diac:
        dediac_fn = _SCHEME_DEDIAC.get(scheme, _default_dediac)
        s = dediac_fn(s)
    if not split_morphs:
        return [s] if s else [surface_word]
    parts = [p for p in s.split("_") if p]
    return parts if parts else ([s] if s else [surface_word])


@dataclass
class CamelCandidate:
    rank: int  # 0-based
    mle_score: float | None
    pos_lex_logprob: float | None
    lex_logprob: float | None
    analysis_raw: dict[str, Any]
    analysis_export: dict[str, Any]
    segments: list[str]
    top_diac: str | None


def build_word_candidates(engine: CamelEngine, word: str) -> list[CamelCandidate]:
    """All MLE analyses (up to engine ``top``) with mechanical segments each."""
    w = (word or "").strip()
    if not w:
        return []
    dis_list = engine.mle.disambiguate([w])
    if not dis_list:
        return []
    d = dis_list[0]
    analyses = d.analyses or []
    logger.info(
        "build_word_candidates: %r -> %s scored analysis(ies) (engine top=%s)",
        w,
        len(analyses),
        engine.top,
    )
    out: list[CamelCandidate] = []
    for i, sa in enumerate(analyses):
        raw: dict[str, Any] = (
            sa.analysis if isinstance(getattr(sa, "analysis", None), dict) else {}
        )
        segs = mechanical_morph_segments(
            raw,
            engine.morph_scheme,
            w,
            split_morphs=engine.split_morphs,
            diac=engine.diac,
        )
        cand = CamelCandidate(
            rank=i,
            mle_score=float(sa.score) if sa.score is not None else None,
            pos_lex_logprob=(
                float(sa.pos_lex_logprob)
                if sa.pos_lex_logprob is not None
                else None
            ),
            lex_logprob=(
                float(sa.lex_logprob) if sa.lex_logprob is not None else None
            ),
            analysis_raw=dict(raw),
            analysis_export=export_analysis_features(raw),
            segments=segs,
            top_diac=str(sa.diac) if sa.diac is not None else None,
        )
        out.append(cand)
        logger.debug(
            "build_word_candidates: rank=%s score=%s segments=%s keys=%s",
            i,
            cand.mle_score,
            segs,
            sorted(cand.analysis_export.keys()),
        )
    if not out:
        logger.warning("build_word_candidates: no analyses; fallback tokenizer on %r", w)
        fb = engine.morph.tokenize([w])
        out.append(
            CamelCandidate(
                rank=0,
                mle_score=None,
                pos_lex_logprob=None,
                lex_logprob=None,
                analysis_raw={},
                analysis_export={},
                segments=fb,
                top_diac=None,
            )
        )
    return dedupe_segment_candidates(out)


def dedupe_segment_candidates(cands: list[CamelCandidate]) -> list[CamelCandidate]:
    """Drop later candidates with identical segment tuples (keep best rank)."""
    seen: set[tuple[str, ...]] = set()
    out: list[CamelCandidate] = []
    for c in cands:
        key = tuple(c.segments)
        if key in seen:
            logger.debug("dedupe_segment_candidates: drop duplicate segments rank=%s", c.rank)
            continue
        seen.add(key)
        out.append(c)
    return out
