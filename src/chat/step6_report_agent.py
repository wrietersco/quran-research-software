"""PARI Step 6 report: plan (stream TOC), act (sections + file_search), review, finalize + appendix."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from openai.types.responses import ResponseTextDeltaEvent

from src.chat.bot1_engine import _collect_message_text_from_output_item, model_allows_temperature
from src.chat.step6_knowledge_export import (
    extract_surah_ayah_refs,
    knowledge_markdown_for_appendix,
)
from src.chat.step6_ui_settings import (
    DEFAULT_ACT_INSTRUCTIONS,
    DEFAULT_PLAN_INSTRUCTIONS,
    DEFAULT_REVIEW_INSTRUCTIONS,
    Step6UiSettings,
    load_step6_ui_settings,
    merge_instruction_blocks,
    merged_file_search_vector_ids,
)
from src.db.bot2_synonyms import fetch_latest_bot2_display_lines
from src.db.chat_pipeline import fetch_latest_bot1_analysis_dict, refined_question_text_for_session

STEP6_DEFAULT_TEMPERATURE = 0.35

_HEADING_LINE = re.compile(r"^(#{1,2})\s+(.+)$")


def resolve_step6_model(ui_or_explicit: str | None) -> str:
    s = (ui_or_explicit or "").strip()
    if s:
        return s
    return (
        os.environ.get("OPENAI_MODEL_STEP6") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    ).strip()


def _call_temperature(model: str, ui_temperature: float | None) -> float | None:
    if not model_allows_temperature(model):
        return None
    if ui_temperature is not None:
        return float(ui_temperature)
    return STEP6_DEFAULT_TEMPERATURE


def _make_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key or not str(key).strip():
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    return OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)


def _usage_pair_from_response(resp) -> tuple[int, int]:
    u = getattr(resp, "usage", None)
    if not u:
        return 0, 0
    inp = int(getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", None) or 0)
    out = int(getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", None) or 0)
    return inp, out


def _response_text(resp) -> str:
    ot = getattr(resp, "output_text", None)
    if ot and str(ot).strip():
        return str(ot)
    parts: list[str] = []
    for item in getattr(resp, "output", None) or []:
        itype = getattr(item, "type", None)
        if itype == "message":
            t = _collect_message_text_from_output_item(item)
            if t.strip():
                parts.append(t)
    return "\n".join(parts).strip()


def _stream_text_deltas(
    client: OpenAI,
    *,
    model: str,
    instructions: str,
    user: str,
    vector_store_ids: list[str] | None,
    on_delta: Callable[[str], None],
    cancel_event: threading.Event | None,
    temperature: float | None = None,
) -> tuple[str, int, int]:
    tools: list = []
    vs_ids = [x.strip() for x in (vector_store_ids or []) if x and str(x).strip()]
    if vs_ids:
        tools.append({"type": "file_search", "vector_store_ids": vs_ids})
    include: list[str] = []
    if vs_ids:
        include.append("file_search_call.results")
    kwargs: dict = {
        "model": model,
        "instructions": instructions,
        "input": [{"role": "user", "content": user}],
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
    if include:
        kwargs["include"] = include
    if model_allows_temperature(model):
        kwargs["temperature"] = (
            float(temperature) if temperature is not None else STEP6_DEFAULT_TEMPERATURE
        )
    stream = client.responses.create(**kwargs)
    buf: list[str] = []
    usage_in = 0
    usage_out = 0
    try:
        for event in stream:
            if cancel_event is not None and cancel_event.is_set():
                break
            if getattr(event, "type", None) == "response.completed":
                r = getattr(event, "response", None)
                if r is not None:
                    di, do = _usage_pair_from_response(r)
                    usage_in += di
                    usage_out += do
            if isinstance(event, ResponseTextDeltaEvent):
                d = event.delta or ""
                if d:
                    buf.append(d)
                    on_delta(d)
            elif getattr(event, "type", None) == "response.output_text.delta":
                d = getattr(event, "delta", None) or ""
                if d:
                    buf.append(d)
                    on_delta(d)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    return "".join(buf), usage_in, usage_out


def _complete(
    client: OpenAI,
    *,
    model: str,
    instructions: str,
    user: str,
    vector_store_ids: list[str] | None,
    cancel_event: threading.Event | None,
    temperature: float | None = None,
) -> tuple[str, int, int]:
    if cancel_event is not None and cancel_event.is_set():
        return "", 0, 0
    tools: list = []
    vs_ids = [x.strip() for x in (vector_store_ids or []) if x and str(x).strip()]
    if vs_ids:
        tools.append({"type": "file_search", "vector_store_ids": vs_ids})
    include: list[str] = []
    if vs_ids:
        include.append("file_search_call.results")
    kwargs: dict = {
        "model": model,
        "instructions": instructions,
        "input": [{"role": "user", "content": user}],
    }
    if tools:
        kwargs["tools"] = tools
    if include:
        kwargs["include"] = include
    if model_allows_temperature(model):
        kwargs["temperature"] = (
            float(temperature) if temperature is not None else STEP6_DEFAULT_TEMPERATURE
        )
    resp = client.responses.create(**kwargs)
    if cancel_event is not None and cancel_event.is_set():
        return "", 0, 0
    ui, uo = _usage_pair_from_response(resp)
    return _response_text(resp), ui, uo


def parse_toc_headings(plan_md: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line in (plan_md or "").splitlines():
        m = _HEADING_LINE.match(line.strip())
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    if not out:
        out.append((1, "Theological analysis"))
    return out


def refs_from_knowledge_paths(paths: list[Path]) -> set[tuple[int, int]]:
    s: set[tuple[int, int]] = set()
    for p in paths:
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            s |= extract_surah_ayah_refs(text)
    return s


@dataclass
class Step6ReportResult:
    markdown: str
    toc_text: str
    prompt_tokens: int
    completion_tokens: int
    model: str


def append_step6_extra_angle_to_context_blob(
    context_blob: str, extra_angle_context: str | None
) -> str:
    """Append a one-off angle section for PARI (e.g. from Discuss regenerate)."""
    ang = (extra_angle_context or "").strip()
    if not ang:
        return context_blob
    return context_blob + f"\n## One-off report angle (this run only)\n{ang}\n"


def run_step6_pari_report(
    conn: sqlite3.Connection,
    chat_session_id: str,
    *,
    vector_store_id: str,
    knowledge_md_paths: list[Path],
    model: str | None = None,
    settings: Step6UiSettings | None = None,
    cancel_event: threading.Event | None = None,
    on_toc_delta: Callable[[str], None] | None = None,
    on_section_delta: Callable[[str], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    extra_angle_context: str | None = None,
) -> Step6ReportResult:
    """
    Plan → Act (per heading) → Review verse coverage (programmatic + optional LLM) → Appendix.
    """
    ui = settings if settings is not None else load_step6_ui_settings()
    model_name = resolve_step6_model(model or ui.model)
    eff_temp = _call_temperature(model_name, ui.temperature)
    client = _make_client()
    vs_act = merged_file_search_vector_ids(vector_store_id, ui.extra_vector_store_ids)

    rq = refined_question_text_for_session(conn, chat_session_id) or ""
    bot1 = fetch_latest_bot1_analysis_dict(conn, chat_session_id)
    bot1_json = json.dumps(bot1, ensure_ascii=False, indent=2) if bot1 else "{}"
    sy_lines = fetch_latest_bot2_display_lines(conn, chat_session_id)
    syn_blob = "\n".join(sy_lines) if sy_lines else "(none)"

    context_blob = append_step6_extra_angle_to_context_blob(
        (
            "## Refined question\n"
            f"{rq}\n\n"
            "## Bot 1 (topics / connotations JSON)\n```json\n{bot1_json}\n```\n\n"
            f"## Bot 2 synonyms\n{syn_blob}\n"
        ),
        extra_angle_context,
    )

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    plan_instructions = merge_instruction_blocks(
        ui.shared_system_preamble,
        ui.plan_instructions,
        DEFAULT_PLAN_INSTRUCTIONS,
    )
    act_instructions = merge_instruction_blocks(
        ui.shared_system_preamble,
        ui.act_instructions,
        DEFAULT_ACT_INSTRUCTIONS,
    )
    review_instructions = merge_instruction_blocks(
        ui.shared_system_preamble,
        ui.review_instructions,
        DEFAULT_REVIEW_INSTRUCTIONS,
    )

    # --- Plan (stream) ---
    status("Plan: drafting table of contents…")
    plan_user = (
        f"{context_blob}\n"
        "Create the TOC now. Headings only, markdown format."
    )

    def _toc_d(delta: str) -> None:
        if on_toc_delta:
            on_toc_delta(delta)

    toc_raw, p_in, p_out = _stream_text_deltas(
        client,
        model=model_name,
        instructions=plan_instructions,
        user=plan_user,
        vector_store_ids=None,
        on_delta=_toc_d,
        cancel_event=cancel_event,
        temperature=eff_temp,
    )
    sum_in = p_in
    sum_out = p_out
    headings = parse_toc_headings(toc_raw)

    status(f"Act: writing {len(headings)} sections…")

    body_parts: list[str] = [f"# Report\n\n{toc_raw}\n\n---\n\n"]

    for level, title in headings:
        if cancel_event is not None and cancel_event.is_set():
            break
        status(f"Section: {title}")
        if on_section_delta:
            on_section_delta(f"\n\n## {title}\n\n")

        prefix = "#" * min(level, 3) + " "
        user_sec = (
            f"{context_blob}\n\n"
            f"Write this part of the report only: **{title}**\n"
            f"Begin the section with markdown heading: {prefix}{title}\n"
            "Include relevant Qur'anic quotes from the knowledge files."
        )
        txt, si, so = _complete(
            client,
            model=model_name,
            instructions=act_instructions,
            user=user_sec,
            vector_store_ids=vs_act,
            cancel_event=cancel_event,
            temperature=eff_temp,
        )
        sum_in += si
        sum_out += so
        body_parts.append(txt + "\n\n")
        if on_section_delta:
            on_section_delta(txt + "\n\n")

    draft = "".join(body_parts)
    k_refs = refs_from_knowledge_paths(knowledge_md_paths)
    d_refs = extract_surah_ayah_refs(draft)
    missing = sorted(k_refs - d_refs)

    max_rounds = max(0, min(20, int(ui.max_review_rounds)))
    round_n = 0
    while missing and round_n < max_rounds:
        round_n += 1
        status(f"Review: covering {len(missing)} cited verses from knowledge files (round {round_n})…")
        miss_str = ", ".join(f"{a}:{b}" for a, b in missing[:80])
        if len(missing) > 80:
            miss_str += ", …"
        patch_user = (
            f"{context_blob}\n\n"
            "The draft may omit some verse references that appear in the knowledge files.\n"
            f"Add one markdown section **Verse coverage — round {round_n}** that briefly discusses "
            f"and quotes (with Arabic) each of these references if they are relevant to the question: "
            f"{miss_str}\n"
            "Use file_search only; quote exactly from files."
        )
        patch, ri, ro = _complete(
            client,
            model=model_name,
            instructions=review_instructions,
            user=patch_user,
            vector_store_ids=vs_act,
            cancel_event=cancel_event,
            temperature=eff_temp,
        )
        sum_in += ri
        sum_out += ro
        body_parts.append(patch + "\n\n")
        if on_section_delta:
            on_section_delta(patch + "\n\n")
        draft = "".join(body_parts)
        d_refs = extract_surah_ayah_refs(draft)
        missing = sorted(k_refs - d_refs)

    status("Finalize: building document…")
    if ui.include_appendix:
        status("Finalize: appending API / pipeline appendix…")
        appendix = knowledge_markdown_for_appendix(conn, chat_session_id)
        cap = max(10_000, int(ui.appendix_max_chars))
        if len(appendix) > cap:
            appendix = (
                appendix[:cap]
                + "\n\n_(Appendix truncated for size; full export remains in session knowledge .md files.)_\n"
            )
        final_md = (
            draft.rstrip()
            + "\n\n---\n\n# Appendix — pipeline and API responses\n\n"
            + appendix
        )
    else:
        final_md = draft.rstrip()
    return Step6ReportResult(
        markdown=final_md,
        toc_text=toc_raw,
        prompt_tokens=sum_in,
        completion_tokens=sum_out,
        model=model_name,
    )


