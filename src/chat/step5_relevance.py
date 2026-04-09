"""Step 5 — CrossEncoder relevance prefilter (optional dependency: sentence-transformers)."""

from __future__ import annotations

import math
import os
import sqlite3
import threading

from src.chat.step5_engine import build_verse_manifest, format_lane_meanings_from_manifest
from src.chat.step5_shortlist_logging import get_step5_shortlist_logger
from src.db.step5_synthesis import Step5MatchRow

# Multilingual MS MARCO cross-encoder (XLM-R; includes Arabic). Valid HF id — do not use the
# non-existent "ms-marco-Multilingual-MiniLM-L12-v2" name.
DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

_MODEL = None
_MODEL_NAME_LOADED: str | None = None


class Step5ShortlistCancelled(Exception):
    """Raised when the user stops SHORTLIST from the UI (between scoring batches)."""


_slist_log = get_step5_shortlist_logger()


def cross_encoder_dependencies_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def configured_cross_encoder_model() -> str:
    return (
        os.environ.get("STEP5_CROSS_ENCODER_MODEL", DEFAULT_CROSS_ENCODER_MODEL).strip()
        or DEFAULT_CROSS_ENCODER_MODEL
    )


def _cross_encoder_allow_hub_fallback() -> bool:
    """If false, only local_files_only=True is attempted (offline / no Hub after cache)."""
    v = (os.environ.get("STEP5_CROSS_ENCODER_HUB_FALLBACK") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def get_cross_encoder():
    """
    Lazy singleton. Prefers ``local_files_only=True`` so routine loads use the HF cache only
    (no Hub download). If the model is not cached yet and hub fallback is allowed, loads once
    with ``local_files_only=False`` to populate the cache.
    """
    global _MODEL, _MODEL_NAME_LOADED
    name = configured_cross_encoder_model()
    if _MODEL is not None and _MODEL_NAME_LOADED == name:
        return _MODEL
    from sentence_transformers import CrossEncoder

    allow_fallback = _cross_encoder_allow_hub_fallback()
    try:
        _MODEL = CrossEncoder(name, local_files_only=True)
    except Exception:  # noqa: BLE001 — cache miss / HF API varies by transformers & hub versions
        if not allow_fallback:
            raise
        _MODEL = CrossEncoder(name, local_files_only=False)
    _MODEL_NAME_LOADED = name
    return _MODEL


def build_relevance_query_text(
    refined_question: str,
    *,
    topic_text: str,
    connotation_text: str,
    find_verses_query: str,
) -> str:
    parts = [
        f"Refined question: {refined_question.strip()}",
        f"Topic: {topic_text.strip()}",
        f"Connotation: {connotation_text.strip()}",
        f"Find-verses query: {find_verses_query.strip()}",
    ]
    return "\n".join(parts)


def ce_logit_to_score_0_10(logit: float) -> float:
    """
    Map CrossEncoder **raw logits** (``model.predict``) to a 0–10 display score.

    MS MARCO–style cross-encoders often output negative logits for query–passage pairs; a plain
    ``10 * sigmoid(logit)`` squashes most values into ~0–0.2, so even a 2% cutoff (0.2) rejects
    almost everything. Here we use a **linear** map from a typical relevance logit band to 0–10,
    then clamp. Override range with env ``STEP5_CE_LOGIT_LO`` / ``STEP5_CE_LOGIT_HI`` (floats).
    """
    if not math.isfinite(logit):
        return 0.0
    try:
        lo = float(os.environ.get("STEP5_CE_LOGIT_LO", "-10"))
        hi = float(os.environ.get("STEP5_CE_LOGIT_HI", "10"))
    except ValueError:
        lo, hi = -10.0, 10.0
    if hi <= lo:
        lo, hi = -10.0, 10.0
    t = (float(logit) - lo) / (hi - lo)
    return max(0.0, min(10.0, t * 10.0))


def score_step5_matches(
    refined_question: str,
    matches: list[Step5MatchRow],
    *,
    batch_size: int = 32,
    conn: sqlite3.Connection | None = None,
    cancel_event: threading.Event | None = None,
    chat_session_id: str | None = None,
) -> list[float]:
    """
    Score each saved verse row for relevance to the session question + topic/connotation.

    When ``conn`` is set, the passage text is verse Arabic plus all Lane entry meanings
    tied to that hit (same manifest roots as Step 5 synthesis).

    When ``cancel_event`` is set, :exc:`Step5ShortlistCancelled` is raised between predict
    chunks (same chunk size as ``batch_size``).

    Returns one float in [0, 10] per match, same order as ``matches``.
    """
    if not matches:
        return []
    sid = chat_session_id or "—"
    bs = max(1, int(batch_size))
    _slist_log.info(
        "SHORTLIST CrossEncoder start session=%s matches=%s predict_batch_size=%s model=%s",
        sid,
        len(matches),
        bs,
        configured_cross_encoder_model(),
    )
    model = get_cross_encoder()
    pairs: list[list[str]] = []
    for m in matches:
        q = build_relevance_query_text(
            refined_question,
            topic_text=m.topic_text,
            connotation_text=m.connotation_text,
            find_verses_query=m.query_text,
        )
        verse = (m.verse_text or "").strip() or "[empty verse text]"
        doc = verse
        if conn is not None:
            meanings = format_lane_meanings_from_manifest(
                build_verse_manifest(conn, find_match_id=m.find_match_id)
            )
            if meanings:
                doc = f"{verse}\n\n{meanings}"
        pairs.append([q, doc])
    out: list[float] = []
    for start in range(0, len(pairs), bs):
        if cancel_event is not None and cancel_event.is_set():
            raise Step5ShortlistCancelled()
        chunk = pairs[start : start + bs]
        _slist_log.debug(
            "SHORTLIST CrossEncoder chunk session=%s pair_index %s..%s (size=%s)",
            sid,
            start,
            start + len(chunk) - 1,
            len(chunk),
        )
        raw = model.predict(chunk, batch_size=bs, show_progress_bar=False)
        for x in raw:
            try:
                out.append(ce_logit_to_score_0_10(float(x)))
            except (TypeError, ValueError):
                out.append(0.0)
    if out:
        _slist_log.info(
            "SHORTLIST CrossEncoder end session=%s scores=%s min=%.4f max=%.4f mean=%.4f",
            sid,
            len(out),
            min(out),
            max(out),
            sum(out) / len(out),
        )
    return out


def min_score_for_threshold_pct(threshold_pct: int) -> float:
    """N%% on a 0–10 scale: e.g. 70 → keep rows with score >= 7.0."""
    p = max(0, min(100, int(threshold_pct)))
    return p / 10.0
