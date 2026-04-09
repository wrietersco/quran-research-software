"""Step 5 SHORTLIST — LLM-based relevance scores (batched Chat Completions)."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from typing import Any

from src.chat.llm_provider import (
    LlmProviderConfig,
    LlmProviderError,
    call_chat_completion,
    shortlist_needs_deepseek_json_preamble,
)
from src.chat.step5_engine import build_verse_manifest, format_lane_meanings_from_manifest
from src.chat.step5_relevance import Step5ShortlistCancelled, build_relevance_query_text
from src.chat.step5_shortlist_logging import get_step5_shortlist_logger
from src.db.step5_synthesis import Step5MatchRow

logger = get_step5_shortlist_logger()

SHORTLIST_LLM_SYSTEM = """You score how relevant each Arabic passage is to the user's research query \
context (refined question, topic, connotation, find-verses query). Output only valid JSON as specified \
in the user message. Scores are floats from 0 (irrelevant) to 10 (highly relevant). Be consistent and \
calibrated across items in the same batch."""

# DeepSeek JSON mode: preamble must mention "json" and describe keys (see llm_provider.call_chat_completion).
DEEPSEEK_SHORTLIST_JSON_PREAMBLE = (
    'Output must be a single valid json object only, with top-level key "scores" whose value is an array. '
    "Each array element must be an object with integer key find_match_id and numeric key relevance_0_10 "
    "(0–10). Include every find_match_id from the user message exactly once. "
    "Do not use markdown fences or any text outside the json object."
)

_MAX_PASSAGE_CHARS = 6000


def _truncate(s: str, max_chars: int) -> str:
    t = (s or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1] + "…"


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```\s*$", t, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return t


def _parse_scores_payload(raw: str, expected_ids: set[int]) -> dict[int, float]:
    t = _strip_json_fence(raw)
    data = json.loads(t)
    if not isinstance(data, dict):
        raise ValueError("root must be object")
    scores = data.get("scores")
    if not isinstance(scores, list):
        raise ValueError("missing scores array")
    out: dict[int, float] = {}
    for item in scores:
        if not isinstance(item, dict):
            continue
        try:
            fid = int(item.get("find_match_id"))
        except (TypeError, ValueError):
            continue
        v = item.get("relevance_0_10")
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        out[fid] = max(0.0, min(10.0, x))
    if set(out.keys()) != expected_ids:
        missing = sorted(expected_ids - set(out.keys()))
        extra = sorted(set(out.keys()) - expected_ids)
        m_head = missing[:25]
        x_head = extra[:25]
        raise ValueError(
            f"scores key mismatch: expected {len(expected_ids)} ids, parsed {len(out)}; "
            f"missing_count={len(missing)} missing_sample={m_head}{'…' if len(missing) > 25 else ''}; "
            f"extra_count={len(extra)} extra_sample={x_head}{'…' if len(extra) > 25 else ''}"
        )
    return out


def _ids_from_scores_response(raw: str) -> set[int]:
    """Ids present in a model ``scores`` array (for logging / lenient diagnostics)."""
    try:
        data = json.loads(_strip_json_fence(raw))
        scores = data.get("scores")
        if not isinstance(scores, list):
            return set()
        out: set[int] = set()
        for item in scores:
            if isinstance(item, dict):
                try:
                    out.add(int(item.get("find_match_id")))
                except (TypeError, ValueError):
                    pass
        return out
    except (json.JSONDecodeError, TypeError, ValueError):
        return set()


def _parse_scores_payload_lenient(raw: str, expected_ids: set[int]) -> dict[int, float]:
    """
    Accept a ``scores`` array even when ids are wrong or incomplete: map what we can,
    fill missing ``expected_ids`` with 0.0. Used only after strict parse fails.
    """
    t = _strip_json_fence(raw)
    data = json.loads(t)
    if not isinstance(data, dict):
        raise ValueError("root must be object")
    scores = data.get("scores")
    if not isinstance(scores, list):
        raise ValueError("missing scores array")
    by_id: dict[int, float] = {}
    for item in scores:
        if not isinstance(item, dict):
            continue
        try:
            fid = int(item.get("find_match_id"))
        except (TypeError, ValueError):
            continue
        v = item.get("relevance_0_10")
        if v is None:
            v = item.get("score")
        if v is None:
            v = item.get("relevance")
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        by_id[fid] = max(0.0, min(10.0, x))
    out: dict[int, float] = {}
    for eid in expected_ids:
        out[eid] = float(by_id.get(eid, 0.0))
    return out


def _one_batch(
    cfg: LlmProviderConfig,
    *,
    items_payload: list[dict[str, Any]],
    expected_ids: set[int],
    retry: bool,
    batch_index: int,
    chat_session_id: str | None,
) -> dict[int, float]:
    user_obj = {
        "items": items_payload,
        "output_shape": {
            "scores": [
                {"find_match_id": iid, "relevance_0_10": "<number 0-10>"}
                for iid in sorted(expected_ids)
            ]
        },
    }
    user_str = json.dumps(user_obj, ensure_ascii=False)
    ds_preamble = (
        DEEPSEEK_SHORTLIST_JSON_PREAMBLE
        if shortlist_needs_deepseek_json_preamble(cfg)
        else None
    )
    sid = chat_session_id or "—"
    logger.debug(
        "SHORTLIST LLM batch %s session=%s provider=%s model=%s user_json_chars=%s find_match_ids=%s",
        batch_index,
        sid,
        cfg.provider,
        cfg.model,
        len(user_str),
        sorted(expected_ids),
    )
    last_raw = ""
    attempts = 2 if retry else 1
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            res = call_chat_completion(
                cfg,
                system_prompt=SHORTLIST_LLM_SYSTEM,
                user_json_payload=user_str,
                deepseek_json_preamble=ds_preamble,
            )
            last_raw = res.text or ""
            parsed = _parse_scores_payload(last_raw, expected_ids)
            logger.info(
                "SHORTLIST LLM batch %s session=%s OK attempt=%s/%s ids=%s "
                "prompt_tokens=%s completion_tokens=%s scores=%s",
                batch_index,
                sid,
                attempt,
                attempts,
                sorted(expected_ids),
                res.prompt_tokens,
                res.completion_tokens,
                {k: round(parsed[k], 3) for k in sorted(parsed.keys())},
            )
            return parsed
        except LlmProviderError as e:
            last_err = e
            logger.error(
                "SHORTLIST LLM batch %s session=%s API error attempt=%s/%s: %s",
                batch_index,
                sid,
                attempt,
                attempts,
                e,
            )
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            head = last_raw[:2000] if last_raw else "(empty assistant content)"
            logger.warning(
                "SHORTLIST LLM batch %s session=%s parse error attempt=%s/%s: %s; response_head=%r",
                batch_index,
                sid,
                attempt,
                attempts,
                e,
                head,
            )
            if isinstance(e, ValueError) and "scores key mismatch" in str(e) and last_raw.strip():
                try:
                    loose = _parse_scores_payload_lenient(last_raw, expected_ids)
                    returned = _ids_from_scores_response(last_raw)
                    missing = sorted(expected_ids - returned)
                    logger.warning(
                        "SHORTLIST LLM batch %s session=%s LENIENT parse applied: "
                        "filled missing ids with 0.0 (model keys did not match). missing_sample=%s",
                        batch_index,
                        sid,
                        missing[:15],
                    )
                    return loose
                except (json.JSONDecodeError, ValueError, TypeError) as le:
                    logger.debug(
                        "SHORTLIST LLM lenient parse failed for batch %s: %s",
                        batch_index,
                        le,
                    )
    assert last_err is not None
    raise last_err


def score_step5_matches_with_llm(
    refined_question: str,
    matches: list[Step5MatchRow],
    *,
    conn: sqlite3.Connection,
    cfg: LlmProviderConfig,
    batch_size: int = 8,
    cancel_event: threading.Event | None = None,
    chat_session_id: str | None = None,
) -> tuple[list[float], str]:
    """
    Returns one float in [0, 10] per match (same order as ``matches``) and provenance ``llm:provider:model``.
    On batch failure after retry, assigns 0.0 to rows in that batch.

    If ``cancel_event`` is set, raises :exc:`~src.chat.step5_relevance.Step5ShortlistCancelled`
    between batches (and during inter-batch rate-limit waits).
    """
    if not matches:
        return [], f"llm:{cfg.provider}:{cfg.model}"
    sid = chat_session_id or "—"
    bs = max(1, min(20, int(batch_size)))
    provenance = f"llm:{cfg.provider}:{cfg.model}"
    by_id: dict[int, float] = {}
    rpm = max(1, int(cfg.rpm_limit))
    pause_s = min(2.0, max(0.0, 60.0 / rpm))
    logger.info(
        "SHORTLIST LLM run start session=%s matches=%s batch_size=%s provider=%s model=%s rpm=%s",
        sid,
        len(matches),
        bs,
        cfg.provider,
        cfg.model,
        rpm,
    )

    batch_num = 0
    for start in range(0, len(matches), bs):
        if cancel_event is not None and cancel_event.is_set():
            raise Step5ShortlistCancelled()
        chunk = matches[start : start + bs]
        items_payload: list[dict[str, Any]] = []
        for m in chunk:
            qblock = build_relevance_query_text(
                refined_question,
                topic_text=m.topic_text,
                connotation_text=m.connotation_text,
                find_verses_query=m.query_text,
            )
            verse = (m.verse_text or "").strip() or "[empty verse text]"
            doc = verse
            meanings = format_lane_meanings_from_manifest(
                build_verse_manifest(conn, find_match_id=m.find_match_id)
            )
            if meanings:
                doc = f"{verse}\n\n{meanings}"
            doc = _truncate(doc, _MAX_PASSAGE_CHARS)
            items_payload.append(
                {
                    "find_match_id": m.find_match_id,
                    "query_context": qblock,
                    "passage": doc,
                }
            )
        expected = {m.find_match_id for m in chunk}
        try:
            got = _one_batch(
                cfg,
                items_payload=items_payload,
                expected_ids=expected,
                retry=True,
                batch_index=batch_num,
                chat_session_id=chat_session_id,
            )
            by_id.update(got)
        except (json.JSONDecodeError, ValueError, LlmProviderError) as e:
            logger.error(
                "SHORTLIST LLM batch %s session=%s FAILED after retries; assigning 0.0 to ids=%s: %s",
                batch_num,
                sid,
                sorted(expected),
                e,
            )
            for m in chunk:
                by_id[m.find_match_id] = 0.0
        batch_num += 1
        if start + bs < len(matches) and pause_s > 0:
            deadline = time.monotonic() + pause_s
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    raise Step5ShortlistCancelled()
                time.sleep(min(0.2, deadline - time.monotonic()))

    scores = [float(by_id.get(m.find_match_id, 0.0)) for m in matches]
    n_zero = sum(1 for s in scores if s <= 0.0)
    if scores:
        logger.info(
            "SHORTLIST LLM run end session=%s scored_rows=%s zero_scores=%s "
            "min=%.4f max=%.4f mean=%.4f",
            sid,
            len(scores),
            n_zero,
            min(scores),
            max(scores),
            sum(scores) / len(scores),
        )
    else:
        logger.info("SHORTLIST LLM run end session=%s no scores", sid)
    return scores, provenance
