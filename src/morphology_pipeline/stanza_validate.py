"""
Sentence-level Stanza Arabic parse + alignment to a pre-tokenized word list (Service D).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StanzaTokenObservation:
    """One input token position after alignment to Stanza words."""

    token_index: int
    surface: str
    upos: str | None = None
    xpos: str | None = None
    lemma: str | None = None
    feats: dict[str, Any] = field(default_factory=dict)
    aligned: bool = False


@dataclass
class StanzaSentenceResult:
    ran: bool
    skipped_reason: str | None = None
    text_parsed: str = ""
    observations: list[StanzaTokenObservation] = field(default_factory=list)


def _flatten_stanza_words(doc: Any) -> list[Any]:
    out = []
    for sent in doc.sentences:
        for w in sent.words:
            out.append(w)
    return out


def align_stanza_to_tokens(tokens: list[str], doc: Any) -> list[StanzaTokenObservation]:
    """
    Match each ``tokens[i]`` to the next unused Stanza word with equal ``.text`` (forward scan).
    """
    flat = _flatten_stanza_words(doc)
    logger.info(
        "align_stanza_to_tokens: %s input tokens, %s stanza words",
        len(tokens),
        len(flat),
    )
    cursor = 0
    obs: list[StanzaTokenObservation] = []
    for i, surf in enumerate(tokens):
        found_idx = None
        for j in range(cursor, len(flat)):
            if flat[j].text == surf:
                found_idx = j
                break
        if found_idx is None:
            logger.warning(
                "align_stanza_to_tokens: no stanza match for index=%s surface=%r cursor=%s",
                i,
                surf,
                cursor,
            )
            obs.append(
                StanzaTokenObservation(token_index=i, surface=surf, aligned=False)
            )
            continue
        w = flat[found_idx]
        cursor = found_idx + 1
        feats: dict[str, Any] = {}
        if w.feats:
            parts = [p.split("=", 1) for p in w.feats.split("|") if "=" in p]
            feats = {a: b for a, b in parts}
        obs.append(
            StanzaTokenObservation(
                token_index=i,
                surface=surf,
                upos=w.upos,
                xpos=w.xpos,
                lemma=w.lemma,
                feats=feats,
                aligned=True,
            )
        )
        logger.debug(
            "align_stanza_to_tokens: [%s] %r -> UPOS=%s LEMMA=%s",
            i,
            surf,
            w.upos,
            w.lemma,
        )
    return obs


def parse_sentence_stanza(
    tokens: list[str],
    *,
    original_text: str | None = None,
) -> StanzaSentenceResult:
    """
    Run Stanza once on ``original_text`` or ``" ".join(tokens)``, align to ``tokens`` order.
    """
    if not tokens:
        return StanzaSentenceResult(ran=False, skipped_reason="no_tokens")
    text = (original_text or "").strip() or " ".join(tokens)
    try:
        import stanza
    except ImportError:
        logger.warning("parse_sentence_stanza: stanza not installed")
        return StanzaSentenceResult(ran=False, skipped_reason="stanza_not_installed")

    try:
        nlp = stanza.Pipeline(
            lang="ar",
            processors="tokenize,pos,lemma",
            download_method=None,
            verbose=False,
        )
    except Exception as e:
        logger.warning("parse_sentence_stanza: pipeline init failed: %s", e)
        return StanzaSentenceResult(
            ran=False, skipped_reason=f"stanza_init_failed:{e!s}"
        )

    logger.info("parse_sentence_stanza: parsing %s chars, %s tokens", len(text), len(tokens))
    doc = nlp(text)
    obs = align_stanza_to_tokens(tokens, doc)
    n_ok = sum(1 for o in obs if o.aligned)
    logger.info(
        "parse_sentence_stanza: aligned %s/%s tokens to Stanza",
        n_ok,
        len(tokens),
    )
    return StanzaSentenceResult(ran=True, text_parsed=text, observations=obs)


def coarse_pos_families(
    camel_pos: str | None, upos: str | None
) -> tuple[str | None, str | None]:
    c = (camel_pos or "").lower()
    u = (upos or "").upper()
    fam_c: str | None = None
    if any(x in c for x in ("noun", "adj", "name", "pron")):
        fam_c = "nominal"
    elif "verb" in c:
        fam_c = "verbal"
    elif "prep" in c or "conj" in c or "prt" in c:
        fam_c = "functional"
    fam_u: str | None = None
    if u in ("NOUN", "PROPN", "ADJ", "PRON", "DET"):
        fam_u = "nominal"
    elif u == "VERB":
        fam_u = "verbal"
    elif u in ("ADP", "CCONJ", "SCONJ", "PART", "AUX"):
        fam_u = "functional"
    return fam_c, fam_u


def observation_to_legacy_validator_dict(
    obs: StanzaTokenObservation | None,
    *,
    camel_pos: str | None = None,
    camel_lex: str | None = None,
) -> dict[str, Any]:
    """Shape compatible with former ``validation_to_dict`` / coarse agreement."""
    if obs is None:
        return {
            "ran": False,
            "skipped_reason": "no_observation",
            "stanza_pos": None,
            "stanza_xpos": None,
            "stanza_lemma": None,
            "stanza_feats": {},
            "agreement_coarse": None,
            "notes": [],
        }
    if not obs.aligned:
        return {
            "ran": True,
            "skipped_reason": "token_not_aligned",
            "stanza_pos": None,
            "stanza_xpos": None,
            "stanza_lemma": None,
            "stanza_feats": {},
            "agreement_coarse": None,
            "notes": [f"unaligned_surface={obs.surface!r}"],
        }

    fam_c, fam_u = coarse_pos_families(camel_pos, obs.upos)
    agree = None
    if fam_c is not None and fam_u is not None:
        agree = fam_c == fam_u
    return {
        "ran": True,
        "skipped_reason": None,
        "stanza_pos": obs.upos,
        "stanza_xpos": obs.xpos,
        "stanza_lemma": obs.lemma,
        "stanza_feats": obs.feats,
        "agreement_coarse": agree,
        "notes": [],
    }
