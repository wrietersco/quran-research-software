"""Load system prompt from docs and call OpenAI Chat Completions."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT

_DOCS_PROMPT = PROJECT_ROOT / "docs" / "chatbot-question-refiner.md"
_REFINER_OVERRIDE = PROJECT_ROOT / "data" / "chat" / "refiner_system_base.txt"

# Must match UI diagnostics
REFINE_TEMPERATURE = 0.4


@dataclass(frozen=True)
class RefineResult:
    """One chat completion from the question refiner."""

    text: str
    model: str
    response_id: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class RefineError(Exception):
    """Configuration or API failure."""


def load_refiner_base_instructions() -> str:
    """Full system message: user override file if present, else docs/chatbot-question-refiner.md."""
    if _REFINER_OVERRIDE.is_file():
        raw = _REFINER_OVERRIDE.read_text(encoding="utf-8")
        if raw.strip():
            return raw.rstrip("\n")
    if not _DOCS_PROMPT.is_file():
        raise RefineError(
            f"Missing system instructions file: {_DOCS_PROMPT}\n"
            "Restore docs/chatbot-question-refiner.md from the repository."
        )
    return _DOCS_PROMPT.read_text(encoding="utf-8")


def save_refiner_base_instructions(text: str) -> None:
    t = (text or "").strip()
    if not t:
        raise ValueError("Refiner system instructions are empty; nothing to save.")
    _REFINER_OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    _REFINER_OVERRIDE.write_text(t + "\n", encoding="utf-8")


def clear_refiner_base_instructions_override() -> None:
    try:
        _REFINER_OVERRIDE.unlink()
    except OSError:
        pass


def load_system_prompt(*, instructions_base: str | None = None) -> str:
    """
    System role content for Chat Completions.
    If ``instructions_base`` is set (e.g. current editor text), it is used as the full system message.
    Otherwise the saved override file or built-in doc is used.
    """
    if instructions_base is not None:
        s = instructions_base.strip()
        if not s:
            raise RefineError(
                "Question refiner system instructions are empty. "
                "Edit the system prompt panel or reset to the built-in doc."
            )
        return s
    return load_refiner_base_instructions()


def extract_refined_question(assistant_text: str) -> str | None:
    """Legacy plain-text refined question between markers."""
    m = re.search(
        r"<<<REFINED_QUESTION>>>\s*(.*?)\s*<<<END_REFINED_QUESTION>>>",
        assistant_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    return m.group(1).strip()


def extract_refined_json(assistant_text: str) -> dict | None:
    """
    Parse <<<REFINED_JSON>>> ... <<<END_REFINED_JSON>>> as JSON.
    Expected shape: {"question": "<text>"}.
    """
    m = re.search(
        r"<<<REFINED_JSON>>>\s*(.*?)\s*<<<END_REFINED_JSON>>>",
        assistant_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "question" not in obj:
        return None
    return obj


def refined_display_text(assistant_text: str) -> str | None:
    """Human-readable refined question: JSON question field or legacy block."""
    j = extract_refined_json(assistant_text)
    if j is not None:
        q = j.get("question")
        return str(q).strip() if q is not None else None
    return extract_refined_question(assistant_text)


def split_assistant_for_display(assistant_text: str) -> tuple[str, str | None]:
    """
    Return (prose without the refined block, refined question text or None).
    """
    refined = refined_display_text(assistant_text)
    if not refined:
        return assistant_text.strip(), None
    prose = assistant_text
    prose = re.sub(
        r"\s*<<<REFINED_JSON>>>.*?<<<END_REFINED_JSON>>>\s*",
        "\n",
        prose,
        flags=re.DOTALL | re.IGNORECASE,
    )
    prose = re.sub(
        r"\s*<<<REFINED_QUESTION>>>.*?<<<END_REFINED_QUESTION>>>\s*",
        "\n",
        prose,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    return prose, refined


def refine_reply(
    messages: list[dict[str, str]],
    *,
    api_key: str | None = None,
    model: str | None = None,
    instructions_base: str | None = None,
) -> RefineResult:
    """
    messages: OpenAI-style list of {"role": "user"|"assistant", "content": "..."}.
    Optional ``instructions_base`` overrides disk/doc for the system message (same as desktop editor).
    """
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key or not key.strip():
        raise RefineError(
            "OpenAI API key not set. Add OPENAI_API_KEY to the project .env file "
            "or export it in your environment, then restart the app."
        )
    model_name = (model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    system = load_system_prompt(instructions_base=instructions_base)

    try:
        from openai import OpenAI
    except ImportError as e:
        raise RefineError(
            "Install the OpenAI SDK: pip install openai"
        ) from e

    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
    chat_messages = [{"role": "system", "content": system}]
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            chat_messages.append({"role": role, "content": content})

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=chat_messages,
            temperature=REFINE_TEMPERATURE,
        )
    except Exception as e:
        raise RefineError(f"OpenAI request failed: {e}") from e

    choice = resp.choices[0] if resp.choices else None
    if not choice or not choice.message or not choice.message.content:
        raise RefineError("Empty response from the model.")
    text = choice.message.content.strip()
    usage = getattr(resp, "usage", None)
    pt = getattr(usage, "prompt_tokens", None) if usage else None
    ct = getattr(usage, "completion_tokens", None) if usage else None
    tt = getattr(usage, "total_tokens", None) if usage else None
    return RefineResult(
        text=text,
        model=getattr(resp, "model", None) or model_name,
        response_id=getattr(resp, "id", None),
        finish_reason=getattr(choice, "finish_reason", None),
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
    )
