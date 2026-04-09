"""
Constrained LLM reranker: choose among library-produced segment candidates only (Service 7).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MORPH_LLM_MODEL = "gpt-4o-mini"


def build_rerank_payload(
    surface: str,
    context_tokens: list[str],
    target_index: int,
    candidates: list[list[str]],
    features_per_candidate: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Structured input for the model (no instruction to invent segments)."""
    return {
        "token": surface,
        "context": context_tokens,
        "target_index_in_context": target_index,
        "candidates": candidates,
        "features": features_per_candidate or [],
    }


def rerank_with_openai(
    payload: dict[str, Any],
    *,
    model: str | None = None,
) -> tuple[int | None, str, dict[str, Any]]:
    """
    Returns ``(chosen_index, reason, raw_meta)``.

    ``chosen_index`` is None if the call failed or JSON was invalid.
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        logger.error("llm_rerank: openai package missing: %s", e)
        return None, "openai_not_installed", {}

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("llm_rerank: OPENAI_API_KEY not set")
        return None, "missing_api_key", {}

    mdl = model or os.getenv("MORPH_LLM_MODEL", DEFAULT_MORPH_LLM_MODEL)
    client = OpenAI(api_key=api_key)

    system = (
        "You are a morphology adjudicator. You MUST choose exactly one candidate by index "
        "(0-based) from the provided candidates list. Each candidate is a list of segment "
        "strings produced by Arabic NLP tools. Do not invent new segments or split differently "
        "than the candidates. Respond with JSON only: {\"chosen_index\": <int>, \"reason\": <string>}."
    )
    user = json.dumps(payload, ensure_ascii=False)

    logger.info(
        "llm_rerank: calling model=%s candidates=%s",
        mdl,
        len(payload.get("candidates") or []),
    )
    logger.debug("llm_rerank: payload_keys=%s", list(payload.keys()))

    try:
        comp = client.chat.completions.create(
            model=mdl,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except Exception as e:
        logger.exception("llm_rerank: API error: %s", e)
        return None, f"api_error:{e!s}", {}

    raw = (comp.choices[0].message.content or "").strip()
    meta = {
        "model": mdl,
        "response_chars": len(raw),
        "finish_reason": getattr(comp.choices[0], "finish_reason", None),
    }
    logger.debug("llm_rerank: raw_response_preview=%r", raw[:500])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("llm_rerank: invalid JSON from model")
        return None, "invalid_json", meta

    idx = data.get("chosen_index")
    reason = str(data.get("reason", ""))
    n_cand = len(payload.get("candidates") or [])
    if not isinstance(idx, int) or idx < 0 or idx >= n_cand:
        logger.error("llm_rerank: chosen_index %s out of range [0,%s)", idx, n_cand)
        return None, "bad_chosen_index", meta

    logger.info("llm_rerank: chosen_index=%s reason_preview=%r", idx, reason[:120])
    return idx, reason, meta
