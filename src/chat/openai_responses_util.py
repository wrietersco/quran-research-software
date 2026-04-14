"""Shared helpers for OpenAI Responses API output text and usage."""

from __future__ import annotations

from src.chat.bot1_engine import _collect_message_text_from_output_item


def response_output_text(resp) -> str:
    """Plain assistant text from a Responses API result."""
    ot = getattr(resp, "output_text", None)
    if ot and str(ot).strip():
        return str(ot).strip()
    parts: list[str] = []
    for item in getattr(resp, "output", None) or []:
        itype = getattr(item, "type", None)
        if itype == "message":
            t = _collect_message_text_from_output_item(item)
            if t.strip():
                parts.append(t.strip())
    return "\n".join(parts).strip()


def response_usage_tokens(resp) -> tuple[int | None, int | None, int | None]:
    u = getattr(resp, "usage", None)
    if not u:
        return None, None, None
    inp = getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", None)
    out = getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", None)
    tot = getattr(u, "total_tokens", None)
    return inp, out, tot
