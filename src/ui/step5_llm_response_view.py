"""Formatted Step 5 LLM API response for the request-log UI (HTML + tk.Text)."""

from __future__ import annotations

import html
import json
import tkinter as tk
from typing import Any

from src.chat.step5_engine import parse_step5_response_json
from src.ui.arabic_display import contains_arabic, shape_arabic_display
from src.ui.material_theme import MaterialColors


def _parsed_dict(
    response_json: str | None, raw_response_text: str | None
) -> dict[str, Any] | None:
    if response_json and str(response_json).strip():
        try:
            obj = json.loads(str(response_json).strip())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    if raw_response_text:
        p = parse_step5_response_json(str(raw_response_text))
        if p is not None:
            return p
    return None


def _payload_str_field(user_payload_json: str | None, key: str) -> str | None:
    """String field from Step 5 user JSON (build_payload: question, topic, connotation, verse_arabic, …)."""
    if not user_payload_json or not str(user_payload_json).strip():
        return None
    try:
        obj = json.loads(str(user_payload_json).strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    v = obj.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _user_question_from_payload(user_payload_json: str | None) -> str | None:
    return _payload_str_field(user_payload_json, "question")


def _escape_body(s: str) -> str:
    return html.escape(s, quote=False)


def _quran_com_verse_url(surah_no: int, ayah_no: int) -> str:
    """Public quran.com URL for a surah/ayah (chapter/verse) reference."""
    return f"https://quran.com/{int(surah_no)}/{int(ayah_no)}"


def _fmt_unknown_fields(d: dict[str, Any], known: set[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k in sorted(d.keys(), key=lambda x: str(x).lower()):
        if k in known:
            continue
        v = d[k]
        if isinstance(v, (dict, list)):
            try:
                val = json.dumps(v, ensure_ascii=False, indent=2)
            except TypeError:
                val = repr(v)
        else:
            val = str(v)
        out.append((str(k), val))
    return out


def build_step5_llm_response_html(
    *,
    job_id: int,
    surah_no: int,
    ayah_no: int,
    job_status: str,
    attempt_count: int,
    llm_call_state: str | None,
    result_id: int | None,
    error_code: str | None,
    error_message: str | None,
    response_json: str | None,
    raw_response_text: str | None,
    user_payload_json: str | None = None,
) -> str:
    """Full HTML document for preview in a browser or clipboard."""
    C = MaterialColors
    parsed = _parsed_dict(response_json, raw_response_text)
    meta_bits = [
        f"Job <strong>#{job_id}</strong>",
        f"Verse <strong>{surah_no}:{ayah_no}</strong>",
        f"Status <strong>{html.escape(job_status)}</strong>",
        f"Attempts {attempt_count}",
    ]
    if llm_call_state and str(llm_call_state).strip():
        meta_bits.append(f"Phase: {html.escape(str(llm_call_state).strip())}")
    if result_id is not None:
        meta_bits.append(f"Result id {result_id}")
    meta_html = " · ".join(meta_bits)

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Step 5 LLM response — job {job_id}</title>",
        "<style>",
        f":root {{ --primary: {C.primary}; --err: {C.error}; --muted: {C.on_surface_variant}; "
        f"--surface: {C.surface_container_high}; --text: {C.on_surface}; }}",
        "body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; padding: 28px 32px; "
        "color: var(--text); background: #f6f7fb; line-height: 1.55; }",
        ".card { background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); "
        "padding: 22px 26px; max-width: 920px; margin: 0 auto; }",
        "h1 { font-size: 1.15rem; font-weight: 650; margin: 0 0 10px; color: var(--primary); }",
        ".meta { font-size: 0.88rem; color: var(--muted); margin-bottom: 22px; line-height: 1.45; }",
        "section { margin-top: 22px; }",
        "h2 { font-size: 0.78rem; text-transform: uppercase; letter-spacing: .06em; "
        "color: var(--muted); margin: 0 0 8px; font-weight: 650; }",
        ".score { font-size: 1.65rem; font-weight: 700; color: var(--primary); margin: 4px 0 0; }",
        ".prose { white-space: pre-wrap; font-size: 0.98rem; }",
        ".err { background: #fde8e8; border-left: 4px solid var(--err); padding: 12px 14px; "
        "border-radius: 0 8px 8px 0; color: #410002; }",
        "pre.raw { white-space: pre-wrap; word-break: break-word; background: var(--surface); "
        "padding: 14px 16px; border-radius: 8px; font-size: 0.82rem; margin: 0; }",
        ".kv { margin: 8px 0 0; padding: 0; list-style: none; }",
        ".kv li { margin: 10px 0; padding: 10px 0; border-top: 1px solid #e8eaf0; }",
        ".kv code { font-size: 0.8rem; color: #5c5f66; }",
        ".kv pre { margin: 8px 0 0; }",
        ".prose a.qurl { color: var(--primary); word-break: break-all; }",
        "</style></head><body><div class='card'>",
        f"<h1>LLM API response</h1><div class='meta'>{meta_html}</div>",
    ]

    qurl = _quran_com_verse_url(surah_no, ayah_no)
    href_esc = html.escape(qurl, quote=True)
    link_text = html.escape(qurl, quote=False)
    parts.append("<section><h2>Verse reference</h2>")
    parts.append(
        "<p class='prose'><a class='qurl' href='"
        f"{href_esc}' target='_blank' rel='noopener noreferrer'>{link_text}</a></p></section>"
    )

    v_ar = _payload_str_field(user_payload_json, "verse_arabic")
    parts.append("<section><h2>Verse text (Arabic)</h2>")
    if v_ar:
        parts.append(
            f"<div class='prose' dir='rtl' style='font-size:1.12rem;line-height:1.7;'>"
            f"{_escape_body(v_ar)}</div>"
        )
    else:
        parts.append("<p class='prose'>(not present in request payload)</p>")
    parts.append("</section>")

    top = _payload_str_field(user_payload_json, "topic")
    parts.append("<section><h2>Topic</h2>")
    if top:
        parts.append(f"<div class='prose'>{_escape_body(top)}</div>")
    else:
        parts.append("<p class='prose'>(not present in request payload)</p>")
    parts.append("</section>")

    con = _payload_str_field(user_payload_json, "connotation")
    parts.append("<section><h2>Connotation / synonym</h2>")
    if con:
        parts.append(f"<div class='prose'>{_escape_body(con)}</div>")
    else:
        parts.append("<p class='prose'>(not present in request payload)</p>")
    parts.append("</section>")

    uq = _user_question_from_payload(user_payload_json)
    parts.append("<section><h2>User question</h2>")
    if uq:
        parts.append(f"<div class='prose'>{_escape_body(uq)}</div>")
    else:
        parts.append("<p class='prose'>(not present in request payload)</p>")
    parts.append("</section>")

    if error_code or error_message:
        ec = html.escape(str(error_code or "").strip())
        em = html.escape(str(error_message or "").strip())
        parts.append(
            "<section><h2>Error</h2>"
            f"<div class='err'><strong>{ec}</strong>"
            f"{'<br>' if em else ''}{em}</div></section>"
        )

    known = {"possibility_score", "exegesis", "symbolic_reasoning"}
    if parsed:
        sc = parsed.get("possibility_score")
        parts.append("<section><h2>Possibility score</h2>")
        if sc is not None and str(sc).strip() != "":
            parts.append(f"<p class='score'>{html.escape(str(sc))}<span style='font-size:.45em;color:var(--muted);'> / 100</span></p>")
        else:
            parts.append("<p class='prose'>(not set)</p>")
        parts.append("</section>")

        ex = parsed.get("exegesis")
        parts.append("<section><h2>Exegesis</h2>")
        if ex is not None and str(ex).strip():
            parts.append(f"<div class='prose'>{_escape_body(str(ex).strip())}</div>")
        else:
            parts.append("<p class='prose'>(empty)</p>")
        parts.append("</section>")

        sy = parsed.get("symbolic_reasoning")
        parts.append("<section><h2>Symbolic reasoning</h2>")
        if sy is not None and str(sy).strip():
            parts.append(f"<div class='prose'>{_escape_body(str(sy).strip())}</div>")
        else:
            parts.append("<p class='prose'>(empty)</p>")
        parts.append("</section>")

        extra = _fmt_unknown_fields(parsed, known)
        if extra:
            parts.append("<section><h2>Other fields</h2><ul class='kv'>")
            for k, v in extra:
                parts.append(
                    "<li><code>"
                    f"{html.escape(k)}</code><pre class='raw'>"
                    f"{_escape_body(v)}</pre></li>"
                )
            parts.append("</ul></section>")
    else:
        parts.append(
            "<section><h2>Parsed JSON</h2>"
            "<p class='prose'>No structured JSON could be parsed from this call yet.</p></section>"
        )

    raw = (raw_response_text or "").strip()
    if raw:
        parts.append(
            "<section><h2>Raw model output</h2>"
            f"<pre class='raw'>{_escape_body(raw)}</pre></section>"
        )

    rj = (response_json or "").strip()
    if rj and rj != raw:
        try:
            pretty = json.dumps(json.loads(rj), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pretty = rj
        parts.append(
            "<section><h2>Stored response_json</h2>"
            f"<pre class='raw'>{_escape_body(pretty)}</pre></section>"
        )

    parts.append("</div></body></html>")
    return "\n".join(parts)


def apply_step5_response_to_tk_text(
    tw: tk.Text,
    *,
    job_id: int,
    surah_no: int,
    ayah_no: int,
    job_status: str,
    attempt_count: int,
    llm_call_state: str | None,
    result_id: int | None,
    error_code: str | None,
    error_message: str | None,
    response_json: str | None,
    raw_response_text: str | None,
    latin_family: str,
    arabic_family: str,
    user_payload_json: str | None = None,
) -> None:
    """Fill a read-only tk.Text with a structured, easy-to-read response view."""

    if not getattr(tw, "_step5_resp_tags_ready", False):
        C = MaterialColors
        tw.tag_configure("sr_title", font=(latin_family, 11, "bold"), foreground=C.primary)
        tw.tag_configure("sr_meta", font=(latin_family, 9), foreground=C.on_surface_variant)
        tw.tag_configure("sr_h2", font=(latin_family, 9, "bold"), foreground=C.on_surface_variant)
        tw.tag_configure("sr_body", font=(latin_family, 10), spacing1=4, spacing3=4)
        tw.tag_configure("sr_ar_body", font=(arabic_family, 11), spacing1=4, spacing3=4, justify="right")
        tw.tag_configure("sr_score", font=(latin_family, 16, "bold"), foreground=C.primary)
        tw.tag_configure("sr_score_note", font=(latin_family, 9), foreground=C.on_surface_variant)
        tw.tag_configure("sr_err", font=(latin_family, 10), foreground=C.error, spacing1=6)
        tw.tag_configure("sr_mono", font=("Consolas", 9), foreground=C.on_surface)
        tw.tag_configure("sr_gap", font=(latin_family, 4))
        tw.tag_configure(
            "sr_url",
            font=(latin_family, 10),
            foreground=C.primary,
            underline=True,
        )
        tw._step5_resp_tags_ready = True  # type: ignore[attr-defined]

    tw.configure(state="normal")
    tw.delete("1.0", tk.END)

    tw.insert(tk.END, "LLM API response\n", "sr_title")
    meta = (
        f"Job #{job_id}   ·   {surah_no}:{ayah_no}   ·   {job_status}   ·   attempts {attempt_count}"
    )
    if llm_call_state and str(llm_call_state).strip():
        meta += f"   ·   phase: {str(llm_call_state).strip()}"
    if result_id is not None:
        meta += f"   ·   result #{result_id}"
    tw.insert(tk.END, meta + "\n\n", "sr_meta")

    tw.insert(tk.END, "Verse reference\n", "sr_h2")
    tw.insert(tk.END, _quran_com_verse_url(surah_no, ayah_no) + "\n\n", "sr_url")

    v_ar = _payload_str_field(user_payload_json, "verse_arabic")
    tw.insert(tk.END, "Verse text (Arabic)\n", "sr_h2")
    if v_ar:
        tw.insert(tk.END, shape_arabic_display(v_ar) + "\n\n", "sr_ar_body")
    else:
        tw.insert(tk.END, "(not present in request payload)\n\n", "sr_body")

    top = _payload_str_field(user_payload_json, "topic")
    tw.insert(tk.END, "Topic\n", "sr_h2")
    if top:
        ttag = "sr_ar_body" if contains_arabic(top) else "sr_body"
        tw.insert(tk.END, shape_arabic_display(top) + "\n\n", ttag)
    else:
        tw.insert(tk.END, "(not present in request payload)\n\n", "sr_body")

    con = _payload_str_field(user_payload_json, "connotation")
    tw.insert(tk.END, "Connotation / synonym\n", "sr_h2")
    if con:
        ctag = "sr_ar_body" if contains_arabic(con) else "sr_body"
        tw.insert(tk.END, shape_arabic_display(con) + "\n\n", ctag)
    else:
        tw.insert(tk.END, "(not present in request payload)\n\n", "sr_body")

    uq = _user_question_from_payload(user_payload_json)
    tw.insert(tk.END, "User question\n", "sr_h2")
    if uq:
        qtag = "sr_ar_body" if contains_arabic(uq) else "sr_body"
        tw.insert(tk.END, shape_arabic_display(uq) + "\n\n", qtag)
    else:
        tw.insert(tk.END, "(not present in request payload)\n\n", "sr_body")

    if error_code or error_message:
        err_line = f"{str(error_code or '').strip()}: {str(error_message or '').strip()}".strip(
            ": "
        )
        tw.insert(tk.END, f"Error\n", "sr_h2")
        tw.insert(tk.END, err_line + "\n\n", "sr_err")

    parsed = _parsed_dict(response_json, raw_response_text)
    known = {"possibility_score", "exegesis", "symbolic_reasoning"}

    if parsed:
        tw.insert(tk.END, "Possibility score\n", "sr_h2")
        sc = parsed.get("possibility_score")
        if sc is not None and str(sc).strip() != "":
            tw.insert(tk.END, str(sc).strip(), "sr_score")
            tw.insert(tk.END, "  / 100\n\n", "sr_score_note")
        else:
            tw.insert(tk.END, "(not set)\n\n", "sr_body")

        def _body_tag(text: str) -> str:
            t = (text or "").strip()
            if not t:
                return "sr_body"
            return "sr_ar_body" if contains_arabic(t) else "sr_body"

        tw.insert(tk.END, "Exegesis\n", "sr_h2")
        ex = parsed.get("exegesis")
        if ex is not None and str(ex).strip():
            tag = _body_tag(str(ex))
            tw.insert(tk.END, shape_arabic_display(str(ex).strip()) + "\n\n", tag)
        else:
            tw.insert(tk.END, "(empty)\n\n", "sr_body")

        tw.insert(tk.END, "Symbolic reasoning\n", "sr_h2")
        sy = parsed.get("symbolic_reasoning")
        if sy is not None and str(sy).strip():
            tag = _body_tag(str(sy))
            tw.insert(tk.END, shape_arabic_display(str(sy).strip()) + "\n\n", tag)
        else:
            tw.insert(tk.END, "(empty)\n\n", "sr_body")

        extra = _fmt_unknown_fields(parsed, known)
        if extra:
            tw.insert(tk.END, "Other fields\n", "sr_h2")
            for k, v in extra:
                tw.insert(tk.END, f"  • {k}\n", "sr_meta")
                tw.insert(tk.END, v.rstrip() + "\n\n", "sr_mono")
    else:
        tw.insert(tk.END, "Parsed JSON\n", "sr_h2")
        tw.insert(
            tk.END,
            "No structured JSON was parsed for this row yet "
            "(job may still be running or failed before save).\n\n",
            "sr_body",
        )

    raw = (raw_response_text or "").strip()
    if raw:
        tw.insert(tk.END, "Raw model output\n", "sr_h2")
        tw.insert(tk.END, raw + "\n\n", "sr_mono")

    rj = (response_json or "").strip()
    if rj:
        try:
            pretty = json.dumps(json.loads(rj), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pretty = rj
        if pretty.strip() != raw:
            tw.insert(tk.END, "Stored response_json\n", "sr_h2")
            tw.insert(tk.END, pretty + "\n", "sr_mono")

    tw.configure(state="disabled")
