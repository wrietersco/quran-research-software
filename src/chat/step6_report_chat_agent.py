"""Step 6 report assistant: intent routing + lightweight PARI Q&A over file_search."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI

from src.chat.step6_report_agent import (
    _call_temperature,
    _complete,
    _make_client,
    resolve_step6_model,
)
from src.chat.step6_ui_settings import Step6UiSettings, merge_instruction_blocks, merged_file_search_vector_ids

CHAT_INTENT_INSTRUCTIONS = """You classify the **latest user message** in a Discuss chat about a Quranic research session report.

Output **only** one JSON object (no markdown fences):
{"action":"answer","angle":null}
or
{"action":"regenerate","angle":"..."}

**Critical — when to use "regenerate":**
Use "regenerate" **only** when the user **explicitly** asks you to produce a **new / rewritten / another PARI report** or clearly requests a **full document redo** (e.g. "write a new report", "rewrite the report", "run PARI again", "regenerate the report", "different angle for the report").

**Always use "answer"** for normal chat: explanations, "do you mean…?", clarifications, definitions, follow-ups, comparisons in prose, or questions about what the report says — even if the topic is deep. Curiosity or conceptual questions are **not** regenerate.

If you use "regenerate", put a short desired angle in "angle", or null."""

CHAT_ANSWER_INSTRUCTIONS = """You are the **Discuss** assistant: chat about the user's session report and knowledge.

Use **file_search** when it helps ground your reply in the indexed report and session materials.

**Format (mandatory):** Reply like a **short chat message**, not a formal report.
- Simple or conversational questions (including "do you mean…?", yes/no, quick definitions): answer in **a few sentences** (about 40–200 words). **No** multi-level headings (### / ####), no essay sections ("Introduction", numbered structure), no mini-outline.
- Use plain paragraphs. At most **one** short bullet list if the user asked for discrete items.
- Only go longer or use light `##` structure if the user **explicitly** asked for a detailed, section-by-section, or comparative treatment.

**Substance:** Be accurate; cite or paraphrase the report/knowledge. Short Arabic quotes only when useful. If the sources do not support a claim, say so briefly."""

CHAT_STYLE_POLISH_INSTRUCTIONS = """You tighten a **Discuss** reply. The draft may be too long or too essay-like.

Rules:
- **Remove** essay-style section headings (###, ####) and lecture structure unless the user clearly asked for a structured analysis.
- Prefer **concise chat**: short paragraphs; for simple questions, **2–8 sentences** when possible.
- Keep facts, nuance, and short quoted Arabic from the draft; do not invent sources.
- If the draft is already short and conversational, change minimally or return it unchanged.

Output **only** the final message text (markdown allowed: light **bold**, bullets if needed)."""


@dataclass(frozen=True)
class Step6ReportChatTurnResult:
    kind: Literal["answer", "regenerate"]
    assistant_markdown: str
    regenerate_angle: str | None
    prompt_tokens: int
    completion_tokens: int
    model: str
    intent_json: dict[str, Any] | None


_JSON_OBJ = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)

# If the model says "regenerate", we still require explicit user wording (PARI report only on request).
_EXPLICIT_REGENERATE_RE = re.compile(
    r"(?:"
    r"\b(?:write|create|generate|produce)\s+(?:a\s+)?(?:new\s+)?(?:pari\s+)?report\b"
    r"|\b(?:new|another|different)\s+(?:pari\s+)?report\b"
    r"|\brewrite\s+(?:the\s+)?report\b"
    r"|\bregenerate\s+(?:the\s+)?report\b"
    r"|\bredo\s+(?:the\s+)?report\b"
    r"|\breplace\s+(?:the\s+)?report\b"
    r"|\brun\s+(?:pari|the\s+pari\s+report|step\s*6)\b"
    r"|\bpari\s+again\b"
    r"|\bfull\s+report\s+again\b"
    r"|\bdifferent\s+angle\s+(?:for\s+)?(?:the\s+)?report\b"
    r"|\bstart\s+(?:a\s+)?(?:new\s+)?report\b"
    r")",
    re.I,
)


def user_explicitly_requests_pari_regeneration(user_message: str) -> bool:
    """True only when the user clearly asks for a new/rewritten PARI report (not conceptual chat)."""
    t = (user_message or "").strip()
    if not t:
        return False
    return bool(_EXPLICIT_REGENERATE_RE.search(t))


def _extract_json_object(text: str) -> dict[str, Any] | None:
    s = (text or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    for m in _JSON_OBJ.finditer(s):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def _format_conversation(conversation: list[tuple[str, str]], *, max_messages: int = 14) -> str:
    tail = conversation[-max_messages:] if len(conversation) > max_messages else conversation
    lines: list[str] = []
    for role, content in tail:
        r = (role or "").strip().lower()
        c = (content or "").strip()
        if not c:
            continue
        lines.append(f"{r.upper()}: {c}")
    return "\n".join(lines)


def classify_intent_json_only(raw: dict[str, Any] | None) -> tuple[str, str | None]:
    if not raw:
        return "answer", None
    act = raw.get("action")
    if isinstance(act, str) and act.strip().lower() == "regenerate":
        ang = raw.get("angle")
        if ang is None:
            return "regenerate", None
        s = str(ang).strip()
        return "regenerate", s if s else None
    return "answer", None


def run_step6_report_chat_turn(
    *,
    vector_store_id: str,
    conversation: list[tuple[str, str]],
    settings: Step6UiSettings,
    model: str | None = None,
    cancel_event: threading.Event | None = None,
) -> Step6ReportChatTurnResult:
    """
    One user turn: route intent; either request regeneration (no PARI write here) or
    Plan → Act (file_search) → Review for a grounded answer.
    ``conversation`` must be non-empty and end with role ``user``.
    """
    if not conversation:
        raise ValueError("conversation is empty")
    if (conversation[-1][0] or "").strip().lower() != "user":
        raise ValueError("conversation must end with a user message")

    ui = settings
    model_name = resolve_step6_model(model or ui.model)
    eff_temp = _call_temperature(model_name, ui.temperature)
    client: OpenAI = _make_client()
    vs_act = merged_file_search_vector_ids(vector_store_id, ui.extra_vector_store_ids)

    conv_block = _format_conversation(conversation)
    intent_user = (
        "Conversation (most recent messages last):\n\n"
        f"{conv_block}\n\n"
        "Classify **only** the last user message."
    )
    intent_instructions = merge_instruction_blocks(
        ui.shared_system_preamble,
        "",
        CHAT_INTENT_INSTRUCTIONS,
    )

    sum_in = 0
    sum_out = 0

    intent_raw, i1, o1 = _complete(
        client,
        model=model_name,
        instructions=intent_instructions,
        user=intent_user,
        vector_store_ids=None,
        cancel_event=cancel_event,
        temperature=eff_temp,
    )
    sum_in += i1
    sum_out += o1
    if cancel_event is not None and cancel_event.is_set():
        return Step6ReportChatTurnResult(
            kind="answer",
            assistant_markdown="",
            regenerate_angle=None,
            prompt_tokens=sum_in,
            completion_tokens=sum_out,
            model=model_name,
            intent_json=None,
        )

    parsed = _extract_json_object(intent_raw)
    action, angle = classify_intent_json_only(parsed)

    last_user = conversation[-1][1].strip()
    if action == "regenerate" and not user_explicitly_requests_pari_regeneration(last_user):
        action = "answer"
        angle = None

    if action == "regenerate":
        tip = (angle or "").strip()
        if tip:
            msg = (
                "Understood — I'll start a **new PARI report** with this one-off angle "
                f"(refined question in the session is unchanged):\n\n_{tip}_"
            )
        else:
            msg = "Understood — I'll start a **new PARI report** (one-off angle not specified)."
        return Step6ReportChatTurnResult(
            kind="regenerate",
            assistant_markdown=msg,
            regenerate_angle=angle,
            prompt_tokens=sum_in,
            completion_tokens=sum_out,
            model=model_name,
            intent_json=parsed,
        )

    prior = _format_conversation(conversation[:-1], max_messages=12)
    answer_instructions = merge_instruction_blocks(
        ui.shared_system_preamble,
        "",
        CHAT_ANSWER_INSTRUCTIONS,
    )
    answer_user = (
        f"Prior context:\n{prior}\n\n---\n\nCurrent question:\n{last_user}"
    )
    draft, i2, o2 = _complete(
        client,
        model=model_name,
        instructions=answer_instructions,
        user=answer_user,
        vector_store_ids=vs_act if vs_act else None,
        cancel_event=cancel_event,
        temperature=eff_temp,
    )
    sum_in += i2
    sum_out += o2
    if cancel_event is not None and cancel_event.is_set():
        return Step6ReportChatTurnResult(
            kind="answer",
            assistant_markdown="",
            regenerate_angle=None,
            prompt_tokens=sum_in,
            completion_tokens=sum_out,
            model=model_name,
            intent_json=parsed,
        )

    polish_instructions = merge_instruction_blocks(
        ui.shared_system_preamble,
        "",
        CHAT_STYLE_POLISH_INSTRUCTIONS,
    )
    polish_user = f"User question:\n{last_user}\n\n## Draft\n{draft}\n"
    final_text, i3, o3 = _complete(
        client,
        model=model_name,
        instructions=polish_instructions,
        user=polish_user,
        vector_store_ids=None,
        cancel_event=cancel_event,
        temperature=eff_temp,
    )
    sum_in += i3
    sum_out += o3

    out_body = (final_text or "").strip() or (draft or "").strip()
    return Step6ReportChatTurnResult(
        kind="answer",
        assistant_markdown=out_body,
        regenerate_angle=None,
        prompt_tokens=sum_in,
        completion_tokens=sum_out,
        model=model_name,
        intent_json=parsed,
    )
