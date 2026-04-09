"""
Service B — CAMeL analyzer path: MLE disambiguation + morphological tokenizer + feature export.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _require_camel() -> None:
    try:
        import camel_tools  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Install camel-tools and data: pip install -r requirements-camel.txt && camel_data -i light"
        ) from e


# Full export for JSON / downstream segment builder
CAMEL_EXPORT_KEYS = (
    "diac",
    "lex",
    "bw",
    "pos",
    "prc3",
    "prc2",
    "prc1",
    "prc0",
    "enc0",
    "enc1",
    "enc2",
    "stem",
    "root",
    "vod",
    "md",
    "gen",
    "num",
    "per",
    "stt",
    "cas",
    "mod",
    "asp",
)


def _is_empty_feat(val: Any) -> bool:
    if val is None:
        return True
    s = str(val).strip()
    if not s:
        return True
    return s.lower() in ("noan", "na", "0", "_")


def export_analysis_features(analysis: dict[str, Any]) -> dict[str, Any]:
    """Copy non-empty CALIMA/CAMeL feature fields for JSON."""
    out: dict[str, Any] = {}
    for k in CAMEL_EXPORT_KEYS:
        v = analysis.get(k)
        if not _is_empty_feat(v):
            out[k] = v
    return out


@dataclass
class CamelDisambiguatedToken:
    """Single token after MLE + morph tokenizer."""

    surface: str
    analysis_raw: dict[str, Any]
    analysis_export: dict[str, Any]
    disambig_score: float | None
    pos_lex_logprob: float | None
    lex_logprob: float | None
    morph_segments: list[str]
    morph_scheme: str
    model_name: str
    n_analyses: int = 0
    top_analysis_diac: str | None = None


class CamelEngine:
    """Caches MLE disambiguator + morphological tokenizer (same scheme for all calls)."""

    def __init__(
        self,
        *,
        model_name: str = "calima-msa-r13",
        morph_scheme: str = "bwtok",
        split_morphs: bool = True,
        diac: bool = False,
        top: int = 1,
    ) -> None:
        _require_camel()
        from camel_tools.disambig.mle import MLEDisambiguator
        from camel_tools.tokenizers.morphological import MorphologicalTokenizer

        self.model_name = model_name
        self.morph_scheme = morph_scheme
        self.split_morphs = split_morphs
        self.diac = diac
        self._top = top
        logger.info(
            "CamelEngine: loading MLE model=%s top=%s morph_scheme=%s split=%s diac=%s",
            model_name,
            top,
            morph_scheme,
            split_morphs,
            diac,
        )
        self._mle = MLEDisambiguator.pretrained(model_name, top=top)
        self._morph = MorphologicalTokenizer(
            disambiguator=self._mle,
            scheme=morph_scheme,
            split=split_morphs,
            diac=diac,
        )
        logger.info("CamelEngine: ready")

    @property
    def mle(self) -> Any:
        return self._mle

    @property
    def morph(self) -> Any:
        return self._morph

    @property
    def top(self) -> int:
        return self._top

    def analyze_token(self, word: str) -> CamelDisambiguatedToken:
        """Disambiguate a single surface token (list of one word to CAMeL)."""
        w = (word or "").strip()
        logger.info("CamelEngine.analyze_token: input=%r", w)
        if not w:
            return CamelDisambiguatedToken(
                surface="",
                analysis_raw={},
                analysis_export={},
                disambig_score=None,
                pos_lex_logprob=None,
                lex_logprob=None,
                morph_segments=[],
                morph_scheme=self.morph_scheme,
                model_name=self.model_name,
                n_analyses=0,
                top_analysis_diac=None,
            )

        from .camel_candidates import build_word_candidates

        cands = build_word_candidates(self, w)
        n_an = len(cands)
        logger.debug("CamelEngine.analyze_token: %r -> %s candidate(s)", w, n_an)

        if not cands:
            logger.warning("CamelEngine.analyze_token: no candidates for %r", w)
            return CamelDisambiguatedToken(
                surface=w,
                analysis_raw={},
                analysis_export={},
                disambig_score=None,
                pos_lex_logprob=None,
                lex_logprob=None,
                morph_segments=[],
                morph_scheme=self.morph_scheme,
                model_name=self.model_name,
                n_analyses=0,
                top_analysis_diac=None,
            )

        top_c = cands[0]
        raw = dict(top_c.analysis_raw)
        exported = dict(top_c.analysis_export)
        morph_segs = list(top_c.segments)

        logger.info(
            "CamelEngine.analyze_token: best score=%s pos_lex_logprob=%s lex_logprob=%s diac_top=%r",
            top_c.mle_score,
            top_c.pos_lex_logprob,
            top_c.lex_logprob,
            top_c.top_diac,
        )
        logger.debug(
            "CamelEngine.analyze_token: exported_keys=%s morph_segments=%s",
            sorted(exported.keys()),
            morph_segs,
        )

        return CamelDisambiguatedToken(
            surface=w,
            analysis_raw=raw,
            analysis_export=exported,
            disambig_score=top_c.mle_score,
            pos_lex_logprob=top_c.pos_lex_logprob,
            lex_logprob=top_c.lex_logprob,
            morph_segments=morph_segs,
            morph_scheme=self.morph_scheme,
            model_name=self.model_name,
            n_analyses=n_an,
            top_analysis_diac=top_c.top_diac,
        )
