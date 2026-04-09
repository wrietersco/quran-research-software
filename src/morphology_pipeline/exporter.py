"""
Service F — structured JSON (and helpers for CSV / prompts later).
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def export_json(data: Any, *, indent: int = 2, ensure_ascii: bool = False) -> str:
    s = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    logger.debug("export_json: bytes=%s", len(s.encode("utf-8")))
    return s


def token_record_to_dict(
    *,
    token_id: int,
    surface: str,
    normalized: str,
    lemma: str | None,
    pos: str | None,
    segments: list[dict[str, Any]],
    camel_block: dict[str, Any],
    validator_block: dict[str, Any] | None,
    confidence: float,
    rules_applied: list[str],
) -> dict[str, Any]:
    """Assemble the recommended per-token schema."""
    rec = {
        "token_id": token_id,
        "surface": surface,
        "normalized": normalized,
        "lemma": lemma,
        "pos": pos,
        "segments": segments,
        "camel": camel_block,
        "validator": validator_block,
        "confidence": round(confidence, 4),
        "rules_applied": list(rules_applied),
    }
    logger.info(
        "token_record_to_dict: token_id=%s segments=%s confidence=%s",
        token_id,
        len(segments),
        confidence,
    )
    return rec
