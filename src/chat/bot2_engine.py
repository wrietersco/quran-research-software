"""Bot 2 — Arabic synonyms for one Bot 1 connotation via Responses API + tool call."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from src.chat.bot1_engine import model_allows_temperature
from src.config import PROJECT_ROOT

_BOT2_DOC = PROJECT_ROOT / "docs" / "bot2-arabic-synonyms-system.md"
_BOT2_BASE_OVERRIDE = PROJECT_ROOT / "data" / "chat" / "bot2_system_base.txt"
BOT2_TEMPERATURE_DEFAULT = 0.2

TOOL_SAVE_SYNONYMS_RESPONSES: dict = {
    "type": "function",
    "name": "save_arabic_synonyms",
    "description": (
        "Persist Arabic synonyms for the given connotation. "
        "Call exactly once with synonyms_json: a JSON string {\"synonyms\": [\"...\", ...]}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "synonyms_json": {
                "type": "string",
                "description": 'Stringified JSON: {"synonyms": ["مرادف1", ...]} — Arabic strings only.',
            }
        },
        "required": ["synonyms_json"],
    },
    "strict": False,
}


def resolve_bot2_model(ui_or_explicit: str | None) -> str:
    s = (ui_or_explicit or "").strip()
    if s:
        return s
    return (
        (os.environ.get("OPENAI_MODEL_BOT2") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini")
    ).strip()


class Bot2Error(Exception):
    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail if detail is not None else message


class Bot2Cancelled(Bot2Error):
    """Raised when the user stops Bot 2 (before or right after the API response)."""

    def __init__(self) -> None:
        super().__init__("Bot 2 stopped by user.")


@dataclass(frozen=True)
class Bot2Result:
    synonyms: list[str]
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
        raise Bot2Error(f"No ``` block found in {path}")
    return m.group(1).strip()


def load_bot2_base_instructions() -> str:
    """Core system text: user override file if present, else first ``` block in the doc."""
    if _BOT2_BASE_OVERRIDE.is_file():
        raw = _BOT2_BASE_OVERRIDE.read_text(encoding="utf-8")
        if raw.strip():
            return raw.rstrip("\n")
    if not _BOT2_DOC.is_file():
        raise Bot2Error(f"Missing {_BOT2_DOC}")
    return _extract_first_fenced_block(_BOT2_DOC)


def save_bot2_base_instructions(text: str) -> None:
    """Persist editable core instructions; used on the next run and after restart."""
    t = (text or "").strip()
    if not t:
        raise ValueError("Bot 2 core instructions are empty; nothing to save.")
    _BOT2_BASE_OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    _BOT2_BASE_OVERRIDE.write_text(t + "\n", encoding="utf-8")


def clear_bot2_base_instructions_override() -> None:
    """Remove saved override so the built-in doc ``` block is used again."""
    try:
        _BOT2_BASE_OVERRIDE.unlink()
    except OSError:
        pass


def bot2_instructions_suffix(max_synonyms: int) -> str:
    """Dynamic suffix: synonym cap (clamped 1–30) + save_arabic_synonyms tool instructions."""
    max_n = max(1, min(30, int(max_synonyms)))
    return (
        f"\n\n## Synonym count limit\n"
        f"Return **at most {max_n}** synonyms in the `synonyms` array.\n\n"
        "## Persistence (application tool)\n"
        "You **must** call **`save_arabic_synonyms`** exactly once with **`synonyms_json`**: "
        "a string containing valid JSON `{{\"synonyms\": [\"...\", ...]}}` with no markdown fences."
    )


def load_bot2_system_prompt(
    max_synonyms: int,
    *,
    instructions_base: str | None = None,
) -> str:
    """
    Full `instructions` for the Responses API: core + synonym limit + tool persistence.
    If ``instructions_base`` is set, it replaces disk/doc for the core block.
    """
    max_n = max(1, min(30, int(max_synonyms)))
    if instructions_base is None:
        base = load_bot2_base_instructions()
    else:
        base = instructions_base.strip()
    if not base:
        raise Bot2Error(
            "Bot 2 system instructions (core block) are empty. "
            "Edit the Step 2 core instructions or reset to the built-in doc."
        )
    return base + bot2_instructions_suffix(max_n)


def _dict_from_synonyms_json_value(raw) -> dict | None:
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


def _parse_synonyms_from_response(resp) -> list[str] | None:
    for item in getattr(resp, "output", None) or []:
        itype = getattr(item, "type", None)
        if itype != "function_call":
            continue
        name = getattr(item, "name", None)
        if name != "save_arabic_synonyms":
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
        got = _dict_from_synonyms_json_value(args.get("synonyms_json"))
        if got and "synonyms" in got:
            return _normalize_synonym_list(got.get("synonyms"))

    for item in getattr(resp, "output", None) or []:
        itype = getattr(item, "type", None)
        if itype == "message":
            blob = _collect_message_text_from_output_item(item)
            if blob.strip():
                direct = _extract_json_object_from_text(blob)
                if direct and "synonyms" in direct:
                    return _normalize_synonym_list(direct.get("synonyms"))

    ot = getattr(resp, "output_text", None) or ""
    if ot and str(ot).strip():
        direct = _extract_json_object_from_text(str(ot))
        if direct and "synonyms" in direct:
            return _normalize_synonym_list(direct.get("synonyms"))
    return None


def _normalize_synonym_list(raw) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
        elif x is not None:
            out.append(str(x).strip())
    return out


def _format_bot2_debug(resp) -> str:
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
            snippet = raw if raw is None or len(str(raw)) <= 800 else str(raw)[:800] + "…"
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


def run_bot2_synonyms(
    *,
    connotation_text: str,
    topic_text: str,
    refined_question: str,
    api_key: str | None = None,
    model: str | None = None,
    vector_store_ids: list[str] | None = None,
    max_synonyms: int = 8,
    temperature: float | None = None,
    cancel_event: threading.Event | None = None,
    instructions_base: str | None = None,
) -> Bot2Result:
    """
    Single Responses API call: synonyms for one connotation.
    If ``instructions_base`` is set, it is used as the core system block; the app still appends
    the synonym limit and tool-persistence text. Otherwise the saved override or built-in doc is used.
    """
    ct = (connotation_text or "").strip()
    if not ct:
        raise Bot2Error("connotation_text is empty.")
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key or not str(key).strip():
        raise Bot2Error("OPENAI_API_KEY is not set.")
    model_name = resolve_bot2_model(model)
    if cancel_event is not None and cancel_event.is_set():
        raise Bot2Cancelled()

    try:
        from openai import OpenAI
    except ImportError as e:
        raise Bot2Error("Install the OpenAI SDK: pip install openai") from e

    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)

    max_n = max(1, min(30, int(max_synonyms)))
    system = load_bot2_system_prompt(max_n, instructions_base=instructions_base)
    user_payload = json.dumps(
        {
            "connotation_text": ct,
            "topic_text": (topic_text or "").strip(),
            "refined_question": (refined_question or "").strip(),
        },
        ensure_ascii=False,
    )
    input_list = [{"role": "user", "content": user_payload}]

    tools: list = [dict(TOOL_SAVE_SYNONYMS_RESPONSES)]
    vs_ids = [x.strip() for x in (vector_store_ids or []) if x and str(x).strip()]
    if vs_ids:
        tools.append({"type": "file_search", "vector_store_ids": vs_ids})

    include: list[str] = []
    if vs_ids:
        include.append("file_search_call.results")

    temp = BOT2_TEMPERATURE_DEFAULT if temperature is None else float(temperature)

    create_kwargs: dict = {
        "model": model_name,
        "instructions": system,
        "input": input_list,
        "tools": tools,
        "tool_choice": {"type": "function", "name": "save_arabic_synonyms"},
    }
    if include:
        create_kwargs["include"] = include
    if model_allows_temperature(model_name):
        create_kwargs["temperature"] = temp

    try:
        resp = client.responses.create(**create_kwargs)
    except Exception as e:
        raise Bot2Error(f"OpenAI request failed: {e}") from e

    if cancel_event is not None and cancel_event.is_set():
        raise Bot2Cancelled()

    syns = _parse_synonyms_from_response(resp)
    if syns is None:
        raise Bot2Error(
            "Could not parse Bot 2 output: expected save_arabic_synonyms(synonyms_json).",
            detail=_format_bot2_debug(resp),
        )
    syns = syns[:max_n]

    pt, ctok, tt = _usage_tokens(resp)
    raw_text = getattr(resp, "output_text", None)

    return Bot2Result(
        synonyms=syns,
        model=getattr(resp, "model", None) or model_name,
        response_id=getattr(resp, "id", None),
        finish_reason=getattr(resp, "status", None),
        prompt_tokens=pt,
        completion_tokens=ctok,
        total_tokens=tt,
        raw_assistant_content=str(raw_text) if raw_text is not None else None,
    )
