"""Bot 1 — topics/connotations JSON via Responses API + tool call to persist analysis."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT

_BOT1_DOC = PROJECT_ROOT / "docs" / "bot1-topics-connotations-system.md"
_BOT1_BASE_OVERRIDE = PROJECT_ROOT / "data" / "chat" / "bot1_system_base.txt"
BOT1_TEMPERATURE = 0.25

# Appended to the core block on every Bot 1 call (Responses API `instructions`).
BOT1_TOOL_PERSISTENCE_SUFFIX = (
    "\n\n## Persistence (application tool)\n"
    "After you have built the complete JSON object, you **must** call the function "
    "**`save_topics_connotations_analysis`** exactly once, with argument **`analysis_json`**: "
    "a string containing the **full** JSON object (same structure as above, valid JSON). "
    "Do not include markdown fences inside the string."
)

# Chat Completions shape (legacy reference only)
TOOL_SAVE_ANALYSIS = {
    "type": "function",
    "function": {
        "name": "save_topics_connotations_analysis",
        "description": (
            "Persist the completed Bot 1 topics/connotations JSON to the application database. "
            "Call exactly once with the full analysis as a JSON string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_json": {
                    "type": "string",
                    "description": (
                        'Stringified JSON: {"question": "...", "analysis": [...]} per Bot 1 template.'
                    ),
                }
            },
            "required": ["analysis_json"],
        },
    },
}

# Responses API: flat function tool (see OpenAI function calling guide)
TOOL_SAVE_ANALYSIS_RESPONSES: dict = {
    "type": "function",
    "name": "save_topics_connotations_analysis",
    "description": (
        "Persist the completed Bot 1 topics/connotations JSON to the application database. "
        "Call exactly once with the full analysis as a JSON string."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "analysis_json": {
                "type": "string",
                "description": (
                    'Stringified JSON: {"question": "...", "analysis": [...]} per Bot 1 template.'
                ),
            }
        },
        "required": ["analysis_json"],
    },
    "strict": False,
}


def resolve_bot1_model(ui_or_explicit: str | None) -> str:
    """
    Model id for Bot 1 (Responses API `model` field).
    Empty override falls back to OPENAI_MODEL_BOT1, then OPENAI_MODEL, then gpt-4o-mini.
    """
    s = (ui_or_explicit or "").strip()
    if s:
        return s
    return (
        (os.environ.get("OPENAI_MODEL_BOT1") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini")
    ).strip()


def model_allows_temperature(model_id: str) -> bool:
    """Reasoning / o-series and gpt-5 family often reject custom temperature."""
    m = model_id.lower().strip()
    if m.startswith("gpt-5"):
        return False
    for prefix in ("o1", "o3", "o4"):
        if m.startswith(prefix):
            return False
    return True


class Bot1Error(Exception):
    """Bot 1 request or parse failure."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail if detail is not None else message


class Bot1Cancelled(Bot1Error):
    """Raised when the user stops Bot 1 (before or right after the API response)."""

    def __init__(self) -> None:
        super().__init__("Bot 1 stopped by user.")


@dataclass(frozen=True)
class Bot1Result:
    analysis: dict
    model: str
    response_id: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    raw_assistant_content: str | None


def _extract_first_fenced_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if not m:
        raise Bot1Error(f"No ``` block found in {path}")
    return m.group(1).strip()


def load_bot1_base_instructions() -> str:
    """Core system text: user override file if present, else first ``` block in the doc."""
    if _BOT1_BASE_OVERRIDE.is_file():
        raw = _BOT1_BASE_OVERRIDE.read_text(encoding="utf-8")
        if raw.strip():
            return raw.rstrip("\n")
    if not _BOT1_DOC.is_file():
        raise Bot1Error(f"Missing {_BOT1_DOC}")
    return _extract_first_fenced_block(_BOT1_DOC)


def save_bot1_base_instructions(text: str) -> None:
    """Persist editable core instructions; used on the next run and after restart."""
    t = (text or "").strip()
    if not t:
        raise ValueError("Bot 1 core instructions are empty; nothing to save.")
    _BOT1_BASE_OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    _BOT1_BASE_OVERRIDE.write_text(t + "\n", encoding="utf-8")


def clear_bot1_base_instructions_override() -> None:
    """Remove saved override so the built-in doc ``` block is used again."""
    try:
        _BOT1_BASE_OVERRIDE.unlink()
    except OSError:
        pass


def load_bot1_system_prompt(*, instructions_base: str | None = None) -> str:
    """
    Full `instructions` string for the Responses API: core + tool persistence suffix.
    If ``instructions_base`` is set (e.g. current Step 1 editor text), it replaces disk/doc.
    """
    if instructions_base is None:
        base = load_bot1_base_instructions()
    else:
        base = instructions_base.strip()
    if not base:
        raise Bot1Error(
            "Bot 1 system instructions (core block) are empty. "
            "Edit the Step 1 core instructions or reset to the built-in doc."
        )
    return base + BOT1_TOOL_PERSISTENCE_SUFFIX


def _dict_from_analysis_json_value(raw) -> dict | None:
    """Tool arg may be a JSON string or an already-parsed object (SDK / proxy variance)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_json_object_from_text(text: str) -> dict | None:
    """Parse first top-level JSON object from assistant text (prose + markdown + JSON)."""
    content = (text or "").strip()
    if not content:
        return None
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z0-9]*\s*\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content).strip()
    start = content.find("{")
    if start < 0:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(content[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _collect_message_text_from_output_item(item) -> str:
    """Best-effort text extraction from a Responses output message item."""
    parts: list[str] = []
    content = getattr(item, "content", None)
    if not content:
        return ""
    for block in content:
        bt = getattr(block, "type", None)
        if bt == "output_text":
            t = getattr(block, "text", None)
            if t:
                parts.append(str(t))
        elif isinstance(block, dict):
            if block.get("type") == "output_text" and block.get("text"):
                parts.append(str(block["text"]))
    return "\n".join(parts)


def _parse_analysis_from_response(resp) -> dict | None:
    """Parse Bot 1 analysis from Responses API output items and output_text."""
    for item in getattr(resp, "output", None) or []:
        itype = getattr(item, "type", None)
        if itype != "function_call":
            continue
        name = getattr(item, "name", None)
        if name != "save_topics_connotations_analysis":
            continue
        raw_args = getattr(item, "arguments", None)
        if raw_args is None:
            continue
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                continue
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            continue
        if not isinstance(args, dict):
            continue
        got = _dict_from_analysis_json_value(args.get("analysis_json"))
        if got:
            return got

    for item in getattr(resp, "output", None) or []:
        itype = getattr(item, "type", None)
        if itype == "message":
            blob = _collect_message_text_from_output_item(item)
            if blob.strip():
                direct = _extract_json_object_from_text(blob)
                if direct and ("question" in direct or "analysis" in direct):
                    return direct
                try:
                    fallback = json.loads(blob.strip())
                except json.JSONDecodeError:
                    fallback = None
                if isinstance(fallback, dict):
                    return fallback

    ot = getattr(resp, "output_text", None) or ""
    if ot and str(ot).strip():
        direct = _extract_json_object_from_text(str(ot))
        if direct and ("question" in direct or "analysis" in direct):
            return direct
        try:
            fallback = json.loads(str(ot).strip())
        except json.JSONDecodeError:
            return None
        if isinstance(fallback, dict):
            return fallback
    return None


def _format_bot1_responses_debug(resp) -> str:
    """Verbose diagnostics when parsing Bot 1 Responses output fails."""
    lines: list[str] = []
    lines.append(f"status: {getattr(resp, 'status', None)!r}")
    lines.append(f"model: {getattr(resp, 'model', None)!r}")
    out = getattr(resp, "output", None) or []
    lines.append(f"output items ({len(out)}):")
    for i, item in enumerate(out):
        itype = getattr(item, "type", None)
        lines.append(f"  [{i}] type={itype!r}")
        if itype == "function_call":
            name = getattr(item, "name", None)
            raw = getattr(item, "arguments", None)
            snippet = raw if raw is None or len(str(raw)) <= 1200 else str(raw)[:1200] + "\n… [truncated]"
            lines.append(f"      name={name!r} arguments={snippet!r}")
    ot = getattr(resp, "output_text", None)
    lines.append("output_text:\n" + (str(ot) if ot else "(empty)"))
    return "\n".join(lines)


def _usage_tokens(resp) -> tuple[int | None, int | None, int | None]:
    u = getattr(resp, "usage", None)
    if not u:
        return None, None, None
    inp = getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", None)
    out = getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", None)
    tot = getattr(u, "total_tokens", None)
    return inp, out, tot


def run_bot1(
    refined_question: dict,
    *,
    api_key: str | None = None,
    model: str | None = None,
    vector_store_ids: list[str] | None = None,
    temperature: float | None = None,
    cancel_event: threading.Event | None = None,
    instructions_base: str | None = None,
) -> Bot1Result:
    """
    refined_question: must include key ``question`` (from refiner JSON).
    Uses Responses API with optional file_search over ``vector_store_ids``.
    If ``instructions_base`` is set, it is used as the core system block (plus the fixed
    tool-persistence suffix). Otherwise the saved override file or built-in doc is used.
    """
    if not isinstance(refined_question, dict) or "question" not in refined_question:
        raise Bot1Error('Refined payload must be a JSON object with a "question" key.')
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key or not str(key).strip():
        raise Bot1Error("OPENAI_API_KEY is not set.")
    model_name = resolve_bot1_model(model)
    if cancel_event is not None and cancel_event.is_set():
        raise Bot1Cancelled()

    try:
        from openai import OpenAI
    except ImportError as e:
        raise Bot1Error("Install the OpenAI SDK: pip install openai") from e

    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)

    system = load_bot1_system_prompt(instructions_base=instructions_base)
    user_payload = json.dumps(refined_question, ensure_ascii=False)
    input_list = [{"role": "user", "content": user_payload}]

    tools: list = [dict(TOOL_SAVE_ANALYSIS_RESPONSES)]
    vs_ids = [x.strip() for x in (vector_store_ids or []) if x and str(x).strip()]
    if vs_ids:
        tools.append({"type": "file_search", "vector_store_ids": vs_ids})

    include: list[str] = []
    if vs_ids:
        include.append("file_search_call.results")

    create_kwargs: dict = {
        "model": model_name,
        "instructions": system,
        "input": input_list,
        "tools": tools,
        "tool_choice": {"type": "function", "name": "save_topics_connotations_analysis"},
    }
    if include:
        create_kwargs["include"] = include
    if model_allows_temperature(model_name):
        create_kwargs["temperature"] = (
            BOT1_TEMPERATURE if temperature is None else float(temperature)
        )

    try:
        resp = client.responses.create(**create_kwargs)
    except Exception as e:
        raise Bot1Error(f"OpenAI request failed: {e}") from e

    if cancel_event is not None and cancel_event.is_set():
        raise Bot1Cancelled()

    analysis = _parse_analysis_from_response(resp)
    if not analysis or not isinstance(analysis, dict):
        debug = _format_bot1_responses_debug(resp)
        raise Bot1Error(
            "Could not parse Bot 1 output: expected tool call "
            "save_topics_connotations_analysis with valid analysis_json, "
            "or assistant output JSON with question/analysis.",
            detail=debug,
        )
    if "question" not in analysis or "analysis" not in analysis:
        preview = json.dumps(analysis, ensure_ascii=False, indent=2)
        if len(preview) > 6000:
            preview = preview[:6000] + "\n… [truncated]"
        raise Bot1Error(
            'Bot 1 JSON must include "question" and "analysis" keys.',
            detail=f"Parsed object keys: {list(analysis.keys())!r}\n\n{preview}",
        )

    pt, ct, tt = _usage_tokens(resp)
    raw_text = getattr(resp, "output_text", None)

    return Bot1Result(
        analysis=analysis,
        model=getattr(resp, "model", None) or model_name,
        response_id=getattr(resp, "id", None),
        finish_reason=getattr(resp, "status", None),
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        raw_assistant_content=str(raw_text) if raw_text is not None else None,
    )
