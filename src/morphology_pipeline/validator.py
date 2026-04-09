"""
Service D — Stanza Arabic pipeline as secondary validator (POS / lemma / feats).

Optional: if ``stanza`` or Arabic models are missing, returns a logged skip result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .stanza_validate import coarse_pos_families

logger = logging.getLogger(__name__)


@dataclass
class StanzaValidationResult:
    ran: bool
    skipped_reason: str | None = None
    stanza_upos: str | None = None
    stanza_xpos: str | None = None
    stanza_lemma: str | None = None
    stanza_feats: dict[str, Any] = field(default_factory=dict)
    agreement_coarse: bool | None = None
    notes: list[str] = field(default_factory=list)


def run_stanza_on_token(
    token_surface: str,
    *,
    context_sentence: str | None = None,
    camel_pos: str | None = None,
    camel_lex: str | None = None,
) -> StanzaValidationResult:
    """
    Run Stanza on ``context_sentence`` if provided, else on ``token_surface`` alone.

    Compares coarse POS family to CAMeL ``pos`` / ``lex`` when available.
    """
    text = (context_sentence or token_surface or "").strip()
    if not text:
        logger.info("run_stanza_on_token: empty text -> skip")
        return StanzaValidationResult(ran=False, skipped_reason="empty_text")

    try:
        import stanza
    except ImportError:
        logger.warning(
            "run_stanza_on_token: stanza not installed (pip install stanza; stanza.download('ar'))"
        )
        return StanzaValidationResult(
            ran=False, skipped_reason="stanza_not_installed"
        )

    try:
        nlp = stanza.Pipeline(
            lang="ar",
            processors="tokenize,pos,lemma",
            download_method=None,
            verbose=False,
        )
    except Exception as e:
        logger.warning(
            "run_stanza_on_token: Stanza pipeline init failed (%s). "
            "Try: python -c \"import stanza; stanza.download('ar')\"",
            e,
        )
        return StanzaValidationResult(
            ran=False, skipped_reason=f"stanza_init_failed:{e!s}"
        )

    logger.info(
        "run_stanza_on_token: parsing text length=%s target_token=%r",
        len(text),
        token_surface,
    )
    doc = nlp(text)
    notes: list[str] = []
    hit_upos = None
    hit_xpos = None
    hit_lemma = None
    hit_feats: dict[str, Any] = {}

    for sent in doc.sentences:
        for w in sent.words:
            if w.text == token_surface:
                hit_upos = w.upos
                hit_xpos = w.xpos
                hit_lemma = w.lemma
                if w.feats:
                    parts = [p.split("=", 1) for p in w.feats.split("|") if "=" in p]
                    hit_feats = {a: b for a, b in parts}
                notes.append(f"matched_stanza_token_text={w.text!r}")
                break
        if hit_upos is not None:
            break

    if hit_upos is None:
        logger.warning(
            "run_stanza_on_token: no Stanza word matched surface=%r in context",
            token_surface,
        )
        return StanzaValidationResult(
            ran=True,
            skipped_reason="token_not_found_in_stanza_doc",
            notes=notes,
        )

    fam_c, fam_u = coarse_pos_families(camel_pos, hit_upos)
    agree = None
    if fam_c is not None and fam_u is not None:
        agree = fam_c == fam_u
    logger.info(
        "run_stanza_on_token: stanza UPOS=%s LEMMA=%s coarse_camel=%s coarse_stanza=%s agreement=%s",
        hit_upos,
        hit_lemma,
        fam_c,
        fam_u,
        agree,
    )
    if camel_lex and hit_lemma:
        logger.debug(
            "run_stanza_on_token: lemma compare camel_lex=%r stanza_lemma=%r",
            camel_lex,
            hit_lemma,
        )

    return StanzaValidationResult(
        ran=True,
        stanza_upos=hit_upos,
        stanza_xpos=hit_xpos,
        stanza_lemma=hit_lemma,
        stanza_feats=hit_feats,
        agreement_coarse=agree,
        notes=notes,
    )


def validation_to_dict(v: StanzaValidationResult) -> dict[str, Any]:
    return {
        "ran": v.ran,
        "skipped_reason": v.skipped_reason,
        "stanza_pos": v.stanza_upos,
        "stanza_xpos": v.stanza_xpos,
        "stanza_lemma": v.stanza_lemma,
        "stanza_feats": v.stanza_feats,
        "agreement_coarse": v.agreement_coarse,
        "notes": v.notes,
    }
