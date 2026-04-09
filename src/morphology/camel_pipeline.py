"""
Two-stage CAMeL Tools pipeline: word tokenization → MLE disambiguation → morphological tokenization.

This is intended for **Modern Standard Arabic** (CALIMA MSA). It is **not** a substitute for
Quranic Arabic Corpus morphology on fully vocalized Uthmani text; use ``quran_token_kalimah``
imports for that. Use this module for MSA sentences, comparison, or experimentation.

Setup (see ``requirements-camel.txt``)::

    pip install -r requirements-camel.txt
    camel_data -i light

Requires Python versions supported by the installed ``camel-tools`` wheel (often 3.8–3.12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

_EXPORT_FEATS = (
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
)


def _require_camel() -> None:
    try:
        import camel_tools  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "camel-tools is not installed. Use: pip install -r requirements-camel.txt "
            "then run: camel_data -i light"
        ) from e


@dataclass
class CamelWordBreakdown:
    """One input word with its top MLE analysis and optional per-word morph segments."""

    word: str
    analysis: dict[str, Any] = field(default_factory=dict)
    morph_segments: list[str] = field(default_factory=list)


@dataclass
class CamelSentenceResult:
    """Full sentence: tokens, per-word analyses, and tokenizer output."""

    tokens: list[str]
    words: list[CamelWordBreakdown]
    morph_flat: list[str]
    model: str
    scheme: str


def load_mle_disambiguator(
    model_name: str = "calima-msa-r13",
    *,
    top: int = 1,
) -> Any:
    _require_camel()
    from camel_tools.disambig.mle import MLEDisambiguator

    return MLEDisambiguator.pretrained(model_name, top=top)


def tokenize_words(text: str) -> list[str]:
    _require_camel()
    from camel_tools.tokenizers.word import simple_word_tokenize

    return simple_word_tokenize(text)


def best_analysis_features(analysis: dict[str, Any]) -> dict[str, Any]:
    """Subset of CALIMA features useful for inspection or export."""
    out: dict[str, Any] = {}
    for k in _EXPORT_FEATS:
        v = analysis.get(k)
        if v is not None and v != "" and v != "NOAN":
            out[k] = v
    return out


def analyze_sentence(
    text: str,
    *,
    model_name: str = "calima-msa-r13",
    scheme: str = "bwtok",
    split_morphs: bool = True,
    diac: bool = False,
    top: int = 1,
) -> CamelSentenceResult:
    """
    Run ``simple_word_tokenize`` → ``MLEDisambiguator.disambiguate`` → ``MorphologicalTokenizer``.

    ``split_morphs``: if True, morphemes are separate strings (underscore split in CAMeL output).
    ``morph_flat`` is the tokenizer output over the **whole** token list (sentence order).
    Each ``CamelWordBreakdown.morph_segments`` is from tokenizing that word alone (same MLE
    behavior as full sentence for this disambiguator, which scores words independently).
    """
    _require_camel()
    from camel_tools.tokenizers.morphological import MorphologicalTokenizer

    mle = load_mle_disambiguator(model_name, top=top)
    tokens = tokenize_words(text)
    disambig = mle.disambiguate(tokens)

    morph_tok = MorphologicalTokenizer(
        disambiguator=mle,
        scheme=scheme,
        split=split_morphs,
        diac=diac,
    )
    morph_flat = morph_tok.tokenize(tokens)

    words: list[CamelWordBreakdown] = []
    for d in disambig:
        w = d.word
        if d.analyses:
            raw = d.analyses[0].analysis
            feats = best_analysis_features(raw if isinstance(raw, dict) else {})
        else:
            feats = {}
        per_word = morph_tok.tokenize([w])
        words.append(
            CamelWordBreakdown(word=w, analysis=feats, morph_segments=per_word)
        )

    return CamelSentenceResult(
        tokens=tokens,
        words=words,
        morph_flat=morph_flat,
        model=model_name,
        scheme=scheme,
    )


def iter_disambiguation_debug(
    text: str,
    *,
    model_name: str = "calima-msa-r13",
    top: int = 1,
) -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield (word, feature_dict) for each token — same as the user's inspect loop."""
    mle = load_mle_disambiguator(model_name, top=top)
    tokens = tokenize_words(text)
    for d in mle.disambiguate(tokens):
        if d.analyses:
            a = d.analyses[0].analysis
            if isinstance(a, dict):
                yield d.word, best_analysis_features(a)
            else:
                yield d.word, {}
        else:
            yield d.word, {}
