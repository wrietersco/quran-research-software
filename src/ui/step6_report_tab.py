"""Step 6 — Report: knowledge load, PARI write, exports, configuration."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, messagebox, filedialog, ttk, scrolledtext
from tkinter.scrolledtext import ScrolledText

from src.ui.material_theme import (
    MaterialColors,
    style_tk_listbox,
    style_tk_text_composer_input,
    style_tk_text_readonly,
)

from src.chat.session_vector_store import (
    create_session_vector_store_async,
    ensure_session_vector_store_in_db,
    session_knowledge_dir,
    session_reports_dir,
)
from src.chat.step6_exports import write_all_formats
from src.chat.step6_knowledge_export import (
    clear_session_step6_knowledge,
    index_report_markdown_on_session_vector_store,
    replace_knowledge_on_vector_store,
)
from src.chat.step6_report_chat_agent import run_step6_report_chat_turn
from src.chat.llm_pricing import split_cost_usd
from src.chat.step6_report_agent import run_step6_pari_report
from src.chat.step6_ui_settings import (
    DEFAULT_ACT_INSTRUCTIONS,
    DEFAULT_PLAN_INSTRUCTIONS,
    DEFAULT_REVIEW_INSTRUCTIONS,
    Step6UiSettings,
    load_step6_ui_settings,
    save_step6_ui_settings,
)
from src.config import get_db_path
from src.db.chat_pipeline import get_chat_session_openai_vector_store_id, upsert_chat_session
from src.db.connection import connect
from src.db.step6_report import (
    insert_step6_report_chat_message,
    insert_step6_report_run,
    latest_step6_report_run,
    list_step6_report_chat_messages,
    list_step6_report_runs,
    update_step6_report_run,
)
from src.openai_platform.resources import OpenAIAdminError


class Step6ReportPane:
    """Builds Step 6 UI; expects host with _root, _current_id, _store, _begin_busy, _end_busy, _busy, _cancel_bot_work."""

    def __init__(self, host: Any, tab: ttk.Frame) -> None:
        self._host = host
        self._tab = tab
        self._paths: dict[str, Path | None] = {}
        self._top_nb: ttk.Notebook | None = None
        self._build()
        self._load_settings_into_widgets()

    def _lf(self) -> tuple[str, int]:
        return ("Segoe UI", 10)

    def _build(self) -> None:
        self._top_nb = ttk.Notebook(self._tab)
        self._top_nb.pack(fill=BOTH, expand=True)
        run_fr = ttk.Frame(self._top_nb)
        cfg_fr = ttk.Frame(self._top_nb)
        disc_fr = ttk.Frame(self._top_nb)
        self._top_nb.add(run_fr, text="Run")
        self._top_nb.add(cfg_fr, text="Configure")
        self._top_nb.add(disc_fr, text="Discuss")
        self._build_run_tab(run_fr)
        self._build_configure_tab(cfg_fr)
        self._build_discuss_tab(disc_fr)

    def _build_run_tab(self, tab: ttk.Frame) -> None:
        host = self._host
        lf = self._lf()

        hdr = ttk.Label(tab, text="Step 6 — Report", font=(lf[0], 12, "bold"))
        hdr.pack(anchor="w", padx=6, pady=(6, 4))

        ttk.Label(
            tab,
            text=(
                "Load: export session pipeline data to .md chunks (≤10 MB each), upload per "
                "Configure → Vector & files.\n"
                "Write: PARI agent uses Configure → System instructions and extra vector stores."
            ),
            wraplength=720,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=6, pady=(0, 6))

        vs_fr = ttk.Frame(tab)
        vs_fr.pack(fill=tk.X, padx=6, pady=4)
        self._vs_var = tk.StringVar(value="Vector store: (not loaded)")
        ttk.Label(vs_fr, textvariable=self._vs_var, font=(lf[0], 9)).pack(anchor="w")

        btn_fr = ttk.Frame(tab)
        btn_fr.pack(fill=tk.X, padx=6, pady=4)

        self._load_btn = ttk.Button(btn_fr, text="Load knowledge → vector store", command=self._on_load)
        self._load_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._write_btn = ttk.Button(btn_fr, text="WRITE report", command=self._on_write)
        self._write_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._stop_btn = ttk.Button(btn_fr, text="Stop", command=self._on_stop, state="disabled")
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._model_var = tk.StringVar(value="")
        ttk.Label(btn_fr, text="Model (optional):").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Entry(btn_fr, textvariable=self._model_var, width=28).pack(side=tk.LEFT)

        dl_fr = ttk.Frame(tab)
        dl_fr.pack(fill=tk.X, padx=6, pady=8)
        ttk.Button(dl_fr, text="Download .md", command=lambda: self._download("md")).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(dl_fr, text="Download .docx", command=lambda: self._download("docx")).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(dl_fr, text="Download .pdf", command=lambda: self._download("pdf")).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(dl_fr, text="Open HTML in browser", command=self._open_html).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self._status_var, font=(lf[0], 9)).pack(anchor="w", padx=6)

        paned = ttk.PanedWindow(tab, orient=tk.VERTICAL)
        paned.pack(fill=BOTH, expand=True, padx=6, pady=6)

        toc_fr = ttk.Labelframe(paned, text="TOC (streaming plan)")
        paned.add(toc_fr, weight=1)
        self._toc_text = scrolledtext.ScrolledText(toc_fr, height=8, wrap=tk.WORD, font=("Consolas", 9))
        self._toc_text.pack(fill=BOTH, expand=True, padx=4, pady=4)

        sec_fr = ttk.Labelframe(paned, text="Sections (streaming + draft)")
        paned.add(sec_fr, weight=2)
        self._section_text = scrolledtext.ScrolledText(
            sec_fr, height=16, wrap=tk.WORD, font=("Consolas", 9)
        )
        self._section_text.pack(fill=BOTH, expand=True, padx=4, pady=4)

        host._step6_load_btn = self._load_btn
        host._step6_write_btn = self._write_btn
        host._step6_stop_btn = self._stop_btn

    def _build_configure_tab(self, tab: ttk.Frame) -> None:
        lf = self._lf()
        canvas = tk.Canvas(tab, highlightthickness=0)
        sb = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(_e: tk.Event) -> str | None:
            canvas.yview_scroll(int(-1 * (_e.delta / 120)), "units")
            return None

        canvas.bind("<MouseWheel>", _on_mousewheel)

        row = 0

        inst = ttk.Labelframe(inner, text="System instructions (prepended to Plan / Act / Review)")
        inst.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
        inner.columnconfigure(0, weight=1)
        row += 1
        ttk.Label(inst, text="Shared preamble (applied to all phases):").pack(anchor="w")
        self._cfg_shared = scrolledtext.ScrolledText(inst, height=4, wrap=tk.WORD, font=("Consolas", 9))
        self._cfg_shared.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        ttk.Label(inst, text="Plan phase (empty → built-in default):").pack(anchor="w")
        self._cfg_plan = scrolledtext.ScrolledText(inst, height=5, wrap=tk.WORD, font=("Consolas", 9))
        self._cfg_plan.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        ttk.Label(inst, text="Act phase — section writing + file_search:").pack(anchor="w")
        self._cfg_act = scrolledtext.ScrolledText(inst, height=6, wrap=tk.WORD, font=("Consolas", 9))
        self._cfg_act.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        ttk.Label(inst, text="Review phase — verse coverage patches:").pack(anchor="w")
        self._cfg_review = scrolledtext.ScrolledText(inst, height=5, wrap=tk.WORD, font=("Consolas", 9))
        self._cfg_review.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        vf = ttk.Labelframe(inner, text="Vector & files (knowledge Load)")
        vf.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
        row += 1
        ttk.Label(
            vf,
            text="Extra vector store IDs (optional, one per line). file_search uses session store first, then these.",
            wraplength=680,
        ).pack(anchor="w", padx=4, pady=2)
        self._cfg_extra_vs = scrolledtext.ScrolledText(vf, height=3, wrap=tk.WORD, font=("Consolas", 9))
        self._cfg_extra_vs.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._cfg_replace_remote = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            vf,
            text="On Load: replace previous knowledge (detach old files from session vector store + clear DB rows)",
            variable=self._cfg_replace_remote,
        ).pack(anchor="w", padx=4)

        self._cfg_delete_openai_objects = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            vf,
            text="After detach: delete OpenAI File objects (not only remove from vector store)",
            variable=self._cfg_delete_openai_objects,
        ).pack(anchor="w", padx=4)

        self._cfg_clear_local = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            vf,
            text="On Load (replace mode): delete entire local knowledge folder before writing",
            variable=self._cfg_clear_local,
        ).pack(anchor="w", padx=4)

        mf = ttk.Labelframe(inner, text="File management")
        mf.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
        row += 1
        bf = ttk.Frame(mf)
        bf.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(bf, text="Open session knowledge folder", command=self._on_open_knowledge_folder).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(
            bf,
            text="Clear session knowledge (OpenAI + DB)",
            command=self._on_clear_session_knowledge,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self._cfg_clear_delete_local = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            mf,
            text="When clearing knowledge: also delete local .md files listed in DB",
            variable=self._cfg_clear_delete_local,
        ).pack(anchor="w", padx=4)

        adv = ttk.Labelframe(inner, text="PARI / model defaults")
        adv.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
        row += 1
        g = ttk.Frame(adv)
        g.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(g, text="Temperature (empty = 0.35; omitted if model forbids):").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self._cfg_temp = tk.StringVar(value="")
        ttk.Entry(g, textvariable=self._cfg_temp, width=8).grid(row=0, column=1, sticky="w")

        ttk.Label(g, text="Max review rounds (0–20):").grid(row=0, column=2, sticky="w", padx=(16, 8))
        self._cfg_max_review = tk.StringVar(value="3")
        ttk.Entry(g, textvariable=self._cfg_max_review, width=5).grid(row=0, column=3, sticky="w")

        ttk.Label(g, text="Appendix max chars:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._cfg_appendix_max = tk.StringVar(value="1500000")
        ttk.Entry(g, textvariable=self._cfg_appendix_max, width=12).grid(row=1, column=1, sticky="w", pady=(8, 0))

        self._cfg_include_appendix = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv, text="Include pipeline/API appendix in report", variable=self._cfg_include_appendix).pack(
            anchor="w", padx=4, pady=(4, 0)
        )

        sf = ttk.Frame(inner)
        sf.grid(row=row, column=0, sticky="ew", padx=6, pady=8)
        row += 1
        ttk.Button(sf, text="Save settings to disk", command=self._on_save_settings).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(sf, text="Reload from disk", command=self._load_settings_into_widgets).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(sf, text="Fill editors with factory defaults", command=self._on_factory_instruction_defaults).pack(
            side=tk.LEFT, padx=(0, 8)
        )

    def _build_discuss_tab(self, tab: ttk.Frame) -> None:
        host = self._host
        latin = getattr(host, "_latin", "Segoe UI")
        arabic = getattr(host, "_arabic", "Segoe UI")

        root = getattr(host, "_root", None)
        outer_pad = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
        outer_pad.pack(fill=BOTH, expand=True)

        ttk.Label(
            outer_pad,
            text="Discuss — report assistant (PARI)",
            style="SectionHeading.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            outer_pad,
            text=(
                "Chat answers are short and conversational (not mini-reports). "
                "A new PARI report runs only when you clearly ask for one "
                "(e.g. write a new report, rewrite the report, run PARI again)."
            ),
            wraplength=720,
            justify=tk.LEFT,
            style="ChatIntro.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        outer = ttk.PanedWindow(outer_pad, orient=tk.HORIZONTAL)
        outer.pack(fill=BOTH, expand=True)

        left = ttk.Frame(outer, style="Card.TFrame", padding=(10, 8))
        right = ttk.Frame(outer, style="Card.TFrame", padding=(14, 10))
        outer.add(left, weight=0)
        outer.add(right, weight=1)

        ttk.Label(left, text="Report runs", style="ChatSection.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(
            left,
            text=(
                "Actions are above the list so they stay visible. Select a run below, then open a format "
                "or folder. Double-click a run for a quick preview (scroll the list itself when there are many runs)."
            ),
            wraplength=280,
            justify=tk.LEFT,
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        br1 = ttk.Frame(left, style="Card.TFrame")
        br1.pack(fill=tk.X, pady=(0, 4))
        for txt, cmd in (
            ("Open HTML", self._discuss_open_html),
            ("Markdown", self._discuss_open_markdown),
            ("PDF", self._discuss_open_pdf),
            ("Word", self._discuss_open_docx),
        ):
            ttk.Button(br1, text=txt, command=cmd, width=11).pack(side=tk.LEFT, padx=(0, 4))

        br2 = ttk.Frame(left, style="Card.TFrame")
        br2.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(br2, text="Open folder", command=self._discuss_open_folder, width=12).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(br2, text="Refresh list", command=self._refresh_report_runs_list, width=12).pack(
            side=tk.LEFT
        )

        ttk.Label(left, text="All runs (newest first)", style="ChatSection.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        list_wrap = tk.Frame(
            left,
            bg=MaterialColors.composer_trough,
            highlightthickness=1,
            highlightbackground=MaterialColors.chat_shell_border,
        )
        list_wrap.pack(fill=BOTH, expand=True)
        self._report_list_ids: list[int] = []
        self._report_listbox = tk.Listbox(
            list_wrap,
            height=8,
            width=36,
            font=(latin, 10),
            selectmode=tk.SINGLE,
            activestyle="none",
        )
        style_tk_listbox(self._report_listbox, latin_family=latin, size=10)
        sb_l = ttk.Scrollbar(list_wrap, orient=VERTICAL, command=self._report_listbox.yview)
        self._report_listbox.configure(yscrollcommand=sb_l.set)
        self._report_listbox.pack(side=tk.LEFT, fill=BOTH, expand=True)
        sb_l.pack(side=tk.RIGHT, fill=tk.Y)
        self._report_listbox.bind("<Double-Button-1>", lambda _e: self._discuss_open_primary_preview())

        ttk.Label(right, text="Messages", style="ChatSection.TLabel").pack(anchor="w", pady=(0, 8))
        self._discuss_chat_shell = tk.Frame(
            right,
            height=300,
            highlightthickness=1,
            highlightbackground=MaterialColors.chat_shell_border,
            bg=MaterialColors.composer_trough,
        )
        self._discuss_chat_shell.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self._discuss_chat_shell.pack_propagate(False)
        log_row = tk.Frame(self._discuss_chat_shell, bg=MaterialColors.surface_container)
        log_row.pack(fill=BOTH, expand=True, padx=3, pady=3)
        self._discuss_chat = tk.Text(
            log_row,
            wrap="word",
            state="disabled",
            font=(arabic, 11),
            relief="flat",
        )
        style_tk_text_readonly(self._discuss_chat, family=arabic, size=11, soft_border=True)
        vsb = ttk.Scrollbar(log_row, orient=VERTICAL, command=self._discuss_chat.yview)
        self._discuss_chat.configure(yscrollcommand=vsb.set)
        self._discuss_chat.pack(side=tk.LEFT, fill=BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._discuss_chat.tag_configure(
            "h_user",
            font=(latin, 10, "bold"),
            foreground=MaterialColors.secondary,
        )
        self._discuss_chat.tag_configure(
            "h_bot",
            font=(latin, 10, "bold"),
            foreground=MaterialColors.success,
        )
        self._discuss_chat.tag_configure("err", font=(latin, 10), foreground=MaterialColors.error)

        inp_fr = ttk.Frame(right, style="Card.TFrame")
        inp_fr.pack(fill=tk.X, pady=(0, 6))
        composer = tk.Frame(
            inp_fr,
            bg=MaterialColors.composer_trough,
            highlightthickness=1,
            highlightbackground=MaterialColors.chat_shell_border,
        )
        composer.pack(fill=tk.X, expand=False)
        inp_row = tk.Frame(composer, bg=MaterialColors.composer_trough)
        inp_row.pack(fill=tk.X, padx=4, pady=4)
        self._discuss_input = ScrolledText(
            inp_row,
            height=4,
            width=40,
            wrap="word",
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
        )
        self._discuss_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        for child in self._discuss_input.winfo_children():
            if isinstance(child, tk.Text):
                style_tk_text_composer_input(child, family=arabic, size=11)
                child.configure(font=(arabic, 11))
        self._discuss_input.configure(bg=MaterialColors.composer_trough)

        icons = getattr(host, "_icons", None)
        s_img = icons.get("send") if icons else None
        sk: dict[str, Any] = {
            "text": "Send",
            "command": self._on_discuss_send,
            "style": "Accent.TButton",
        }
        if s_img:
            sk["image"] = s_img
            sk["compound"] = "left"
        self._discuss_send_btn = ttk.Button(inp_row, **sk)
        self._discuss_send_btn.pack(side=tk.RIGHT, anchor="se", padx=(0, 2), pady=(0, 2))

        ttk.Label(
            right,
            text="Tip: Ctrl+Enter sends. Regenerate phrasing (e.g. “rewrite the report”) switches to Run and starts PARI.",
            style="Hint.TLabel",
            wraplength=640,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(4, 0))

        def _discuss_ctrl_ret(_e: tk.Event) -> str:
            self._on_discuss_send()
            return "break"

        self._discuss_input.bind("<Control-Return>", _discuss_ctrl_ret)
        for child in self._discuss_input.winfo_children():
            if isinstance(child, tk.Text):
                child.bind("<Control-Return>", _discuss_ctrl_ret)

        if root is not None:

            def _discuss_tab_configure(event: tk.Event) -> None:
                if event.widget != tab or getattr(event, "height", 0) < 120:
                    return
                reserve = 340
                avail = max(220, int(event.height) - reserve)
                nh = min(420, max(240, int(avail * 0.48)))
                try:
                    if self._discuss_chat_shell.winfo_height() == nh:
                        return
                    self._discuss_chat_shell.configure(height=nh)
                except tk.TclError:
                    pass

            tab.bind("<Configure>", _discuss_tab_configure, add=True)

    def _append_discuss_chat(self, role: str, text: str) -> None:
        w = self._discuss_chat
        w.configure(state="normal")
        if role == "user":
            w.insert(END, "You\n", ("h_user",))
            w.insert(END, text + "\n\n")
        else:
            w.insert(END, "Assistant\n", ("h_bot",))
            body = text + "\n\n"
            if body.lstrip().startswith("(Error)"):
                w.insert(END, body, ("err",))
            else:
                w.insert(END, body)
        w.configure(state="disabled")
        w.see(END)

    def _reload_discuss_chat_log(self) -> None:
        w = self._discuss_chat
        w.configure(state="normal")
        w.delete("1.0", END)
        w.configure(state="disabled")
        sid = self._sid()
        if not sid:
            return
        try:
            conn = connect(get_db_path())
            try:
                rows = list_step6_report_chat_messages(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            return
        for m in rows:
            self._append_discuss_chat(m.role, m.content)

    def _refresh_report_runs_list(self) -> None:
        if not hasattr(self, "_report_listbox"):
            return
        self._report_listbox.delete(0, END)
        self._report_list_ids.clear()
        sid = self._sid()
        if not sid:
            return
        try:
            conn = connect(get_db_path())
            try:
                runs = list_step6_report_runs(conn, sid, newest_first=True)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            return
        for r in runs:
            self._report_list_ids.append(r.id)
            raw_ts = (r.created_at or "").replace("T", " ")
            ts = raw_ts[:16] if len(raw_ts) >= 16 else raw_ts
            model = (r.model or "—").strip() or "—"
            if len(model) > 26:
                model = model[:23] + "…"
            self._report_listbox.insert(
                END,
                f"Run {r.id} — {r.status} — {ts} — {model}",
            )

    def _discuss_selected_run_id(self) -> int | None:
        if not hasattr(self, "_report_listbox"):
            return None
        sel = self._report_listbox.curselection()
        if not sel:
            return None
        i = int(sel[0])
        if 0 <= i < len(self._report_list_ids):
            return self._report_list_ids[i]
        return None

    def _path_for_report_run(self, run_id: int) -> Path | None:
        sid = self._sid()
        if not sid:
            return None
        try:
            conn = connect(get_db_path())
            try:
                runs = list_step6_report_runs(conn, sid, newest_first=False)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            return None
        for r in runs:
            if r.id == run_id and r.report_dir:
                return Path(r.report_dir)
        return None

    def _open_local_path_default(self, p: Path) -> None:
        host = self._host
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(p)], check=False)
            else:
                subprocess.run(["xdg-open", str(p)], check=False)
        except OSError as e:
            messagebox.showerror("Step 6", str(e), parent=host._root)

    def _discuss_open_report_artifact(self, filename: str, missing_label: str) -> None:
        host = self._host
        rid = self._discuss_selected_run_id()
        if rid is None:
            messagebox.showinfo("Step 6", "Select a report run in the list.", parent=host._root)
            return
        base = self._path_for_report_run(rid)
        if not base or not base.is_dir():
            messagebox.showinfo("Step 6", "No folder for this run.", parent=host._root)
            return
        path = base / filename
        if not path.is_file():
            messagebox.showinfo(
                "Step 6",
                f"{missing_label} not found for this run ({filename}).",
                parent=host._root,
            )
            return
        if filename.endswith(".html"):
            webbrowser.open(path.as_uri())
        else:
            self._open_local_path_default(path)

    def _discuss_open_html(self) -> None:
        self._discuss_open_report_artifact("report.html", "HTML report")

    def _discuss_open_markdown(self) -> None:
        self._discuss_open_report_artifact("report.md", "Markdown report")

    def _discuss_open_pdf(self) -> None:
        self._discuss_open_report_artifact("report.pdf", "PDF report")

    def _discuss_open_docx(self) -> None:
        self._discuss_open_report_artifact("report.docx", "Word report")

    def _discuss_open_primary_preview(self) -> None:
        host = self._host
        rid = self._discuss_selected_run_id()
        if rid is None:
            messagebox.showinfo("Step 6", "Select a report run in the list.", parent=host._root)
            return
        base = self._path_for_report_run(rid)
        if not base or not base.is_dir():
            messagebox.showinfo("Step 6", "No folder for this run.", parent=host._root)
            return
        for name in ("report.html", "report.pdf", "report.md", "report.docx"):
            p = base / name
            if p.is_file():
                if name.endswith(".html"):
                    webbrowser.open(p.as_uri())
                else:
                    self._open_local_path_default(p)
                return
        messagebox.showinfo(
            "Step 6",
            "No report exports found in this run folder yet.",
            parent=host._root,
        )

    def _discuss_open_folder(self) -> None:
        host = self._host
        rid = self._discuss_selected_run_id()
        if rid is None:
            messagebox.showinfo("Step 6", "Select a report run in the list.", parent=host._root)
            return
        base = self._path_for_report_run(rid)
        if not base or not base.is_dir():
            messagebox.showinfo("Step 6", "No folder for this run.", parent=host._root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(base)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(base)], check=False)
            else:
                subprocess.run(["xdg-open", str(base)], check=False)
        except OSError as e:
            messagebox.showerror("Step 6", str(e), parent=host._root)

    def _on_discuss_send(self) -> None:
        host = self._host
        if getattr(host, "_busy", False):
            return
        sid = self._sid()
        if not sid:
            messagebox.showinfo("Step 6", "Select a session first.", parent=host._root)
            return
        raw = self._discuss_input.get("1.0", END).strip()
        if not raw:
            return
        self._discuss_input.delete("1.0", END)
        ss = self._gather_settings()
        try:
            conn = connect(get_db_path())
            try:
                upsert_chat_session(conn, sid, self._title())
                vid = get_chat_session_openai_vector_store_id(conn, sid)
                if not vid:
                    vid = ensure_session_vector_store_in_db(conn, sid, self._title())
                insert_step6_report_chat_message(conn, chat_session_id=sid, role="user", content=raw)
                msgs = list_step6_report_chat_messages(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 6", str(e), parent=host._root)
            return
        if not vid:
            messagebox.showwarning(
                "Step 6",
                "No vector store for this session. Run **Load knowledge** first.",
                parent=host._root,
            )
            return
        self._reload_discuss_chat_log()
        model = (self._model_var.get() or "").strip() or None
        cancel = getattr(host, "_cancel_bot_work", None)
        if cancel is not None:
            cancel.clear()

        conv = [(m.role, m.content) for m in msgs]

        def work() -> None:
            err: str | None = None
            result = None
            try:
                result = run_step6_report_chat_turn(
                    vector_store_id=vid,
                    conversation=conv,
                    settings=ss,
                    model=model,
                    cancel_event=cancel,
                )
            except Exception as e:
                err = str(e)

            def done() -> None:
                if err:
                    host._end_busy("Discuss — error.")
                    self._append_discuss_chat("assistant", f"(Error) {err}")
                    try:
                        c2 = connect(get_db_path())
                        try:
                            insert_step6_report_chat_message(
                                c2,
                                chat_session_id=sid,
                                role="assistant",
                                content=f"(Error) {err}",
                            )
                        finally:
                            c2.close()
                    except (OSError, sqlite3.Error):
                        pass
                    messagebox.showerror("Step 6 — Discuss", err, parent=host._root)
                    return
                if result is None:
                    host._end_busy("")
                    return
                meta = None
                if result.prompt_tokens or result.completion_tokens:
                    meta = json.dumps(
                        {
                            "intent": result.intent_json,
                            "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens,
                            "model": result.model,
                        },
                        ensure_ascii=False,
                    )
                self._append_discuss_chat("assistant", result.assistant_markdown)
                try:
                    c2 = connect(get_db_path())
                    try:
                        insert_step6_report_chat_message(
                            c2,
                            chat_session_id=sid,
                            role="assistant",
                            content=result.assistant_markdown,
                            meta_json=meta,
                        )
                    finally:
                        c2.close()
                except (OSError, sqlite3.Error) as pe:
                    messagebox.showerror("Step 6", str(pe), parent=host._root)
                mname = (result.model or "").strip() or "gpt-4o-mini"
                cin, cout, _ = split_cost_usd(
                    "openai",
                    mname,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
                host._pipeline_step_finish_from_partial(
                    sid,
                    6,
                    agent=True,
                    in_tok=int(result.prompt_tokens),
                    out_tok=int(result.completion_tokens),
                    in_usd=cin,
                    out_usd=cout,
                    models=f"Discuss — {mname}",
                )
                host._end_busy("Discuss — done.")
                if result.kind == "regenerate":
                    ang = (result.regenerate_angle or "").strip()
                    self._on_write(extra_angle_context=ang or None)

            host._root.after(0, done)

        host._begin_busy("Step 6 — Discuss…", op="step6")
        threading.Thread(target=work, daemon=True).start()

    def _text_set(self, w: scrolledtext.ScrolledText, s: str) -> None:
        w.delete("1.0", END)
        w.insert("1.0", s)

    def _text_get(self, w: scrolledtext.ScrolledText) -> str:
        return w.get("1.0", END).rstrip("\n")

    def _load_settings_into_widgets(self) -> None:
        s = load_step6_ui_settings()
        self._model_var.set(s.model)
        self._text_set(self._cfg_shared, s.shared_system_preamble)
        self._text_set(self._cfg_plan, s.plan_instructions)
        self._text_set(self._cfg_act, s.act_instructions)
        self._text_set(self._cfg_review, s.review_instructions)
        self._text_set(self._cfg_extra_vs, "\n".join(s.extra_vector_store_ids))
        self._cfg_replace_remote.set(s.replace_remote_knowledge_on_load)
        self._cfg_delete_openai_objects.set(s.delete_openai_file_objects_after_detach)
        self._cfg_clear_local.set(s.clear_local_knowledge_dir_before_load)
        self._cfg_temp.set("" if s.temperature is None else str(s.temperature))
        self._cfg_max_review.set(str(s.max_review_rounds))
        self._cfg_appendix_max.set(str(s.appendix_max_chars))
        self._cfg_include_appendix.set(s.include_appendix)

    def _gather_settings(self) -> Step6UiSettings:
        def _parse_int(sv: tk.StringVar, default: int, lo: int, hi: int) -> int:
            raw = (sv.get() or "").strip()
            if not raw:
                return default
            try:
                n = int(raw)
            except ValueError:
                return default
            return max(lo, min(hi, n))

        def _parse_opt_float(sv: tk.StringVar) -> float | None:
            raw = (sv.get() or "").strip()
            if not raw:
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        extras = [
            ln.strip()
            for ln in self._text_get(self._cfg_extra_vs).splitlines()
            if ln.strip()
        ]
        return Step6UiSettings(
            model=(self._model_var.get() or "").strip(),
            temperature=_parse_opt_float(self._cfg_temp),
            shared_system_preamble=self._text_get(self._cfg_shared),
            plan_instructions=self._text_get(self._cfg_plan),
            act_instructions=self._text_get(self._cfg_act),
            review_instructions=self._text_get(self._cfg_review),
            extra_vector_store_ids=extras,
            replace_remote_knowledge_on_load=self._cfg_replace_remote.get(),
            delete_openai_file_objects_after_detach=self._cfg_delete_openai_objects.get(),
            clear_local_knowledge_dir_before_load=self._cfg_clear_local.get(),
            max_review_rounds=_parse_int(self._cfg_max_review, 3, 0, 20),
            appendix_max_chars=_parse_int(self._cfg_appendix_max, 1_500_000, 10_000, 50_000_000),
            include_appendix=self._cfg_include_appendix.get(),
        )

    def _on_save_settings(self) -> None:
        ss = self._gather_settings()
        save_step6_ui_settings(ss)
        messagebox.showinfo("Step 6", "Settings saved.", parent=self._host._root)

    def _on_factory_instruction_defaults(self) -> None:
        self._text_set(self._cfg_plan, DEFAULT_PLAN_INSTRUCTIONS)
        self._text_set(self._cfg_act, DEFAULT_ACT_INSTRUCTIONS)
        self._text_set(self._cfg_review, DEFAULT_REVIEW_INSTRUCTIONS)
        self._text_set(self._cfg_shared, "")

    def _on_open_knowledge_folder(self) -> None:
        sid = self._sid()
        if not sid:
            messagebox.showinfo("Step 6", "Select a session first.", parent=self._host._root)
            return
        d = session_knowledge_dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(d)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(d)], check=False)
            else:
                subprocess.run(["xdg-open", str(d)], check=False)
        except OSError as e:
            messagebox.showerror("Step 6", str(e), parent=self._host._root)

    def _on_clear_session_knowledge(self) -> None:
        host = self._host
        sid = self._sid()
        if not sid:
            messagebox.showinfo("Step 6", "Select a session first.", parent=host._root)
            return
        if not messagebox.askyesno(
            "Step 6",
            "Remove all Step 6 knowledge chunks and indexed report files from the "
            "session vector store (OpenAI) and clear the related database rows?",
            parent=host._root,
        ):
            return
        ss = self._gather_settings()
        del_local = self._cfg_clear_delete_local.get()
        try:
            conn = connect(get_db_path())
            try:
                n = clear_session_step6_knowledge(
                    conn,
                    sid,
                    delete_openai_file_objects=ss.delete_openai_file_objects_after_detach,
                    delete_local_files=del_local,
                )
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 6", str(e), parent=host._root)
            return
        self.refresh_vector_status()
        messagebox.showinfo("Step 6", f"Cleared {n} knowledge record(s).", parent=host._root)

    def _sid(self) -> str | None:
        sid = getattr(self._host, "_current_id", None)
        return str(sid) if sid else None

    def _title(self) -> str | None:
        sid = self._sid()
        if not sid:
            return None
        st = getattr(self._host, "_store", None)
        if not st:
            return None
        s = st.get(sid)
        return s.title if s else None

    def refresh_vector_status(self) -> None:
        sid = self._sid()
        if not sid:
            self._vs_var.set("Vector store: (no session)")
            return
        try:
            conn = connect(get_db_path())
            try:
                vid = get_chat_session_openai_vector_store_id(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            vid = None
        if vid:
            self._vs_var.set(f"Vector store: {vid}")
        else:
            self._vs_var.set(
                "Vector store: not created yet (new session may still be provisioning; use Load to retry)"
            )
        if hasattr(self, "_report_listbox"):
            self._refresh_report_runs_list()
            self._reload_discuss_chat_log()

    def _on_stop(self) -> None:
        ev = getattr(self._host, "_cancel_bot_work", None)
        if ev is not None:
            ev.set()
        st = getattr(self._host, "_status", None)
        if st is not None and hasattr(st, "set"):
            st.set("Stopping Step 6…")

    def _on_load(self) -> None:
        host = self._host
        if getattr(host, "_busy", False):
            return
        sid = self._sid()
        if not sid:
            messagebox.showinfo("Step 6", "Select a session first.", parent=host._root)
            return
        title = self._title()
        ss = self._gather_settings()
        host._begin_busy("Step 6 — Loading knowledge…", op="step6")
        host._pipeline_step_start(sid, 6)
        self._toc_text.delete("1.0", END)
        self._section_text.delete("1.0", END)
        self._status_var.set(
            "Checking vector store for PARI; creating and attaching one if missing "
            "(older sessions), then uploading knowledge…"
        )

        def work() -> None:
            err: str | None = None
            n_files = 0
            try:
                conn = connect(get_db_path())
                try:
                    upsert_chat_session(conn, sid, title)
                    _, paths = replace_knowledge_on_vector_store(
                        conn,
                        sid,
                        title,
                        replace_remote=ss.replace_remote_knowledge_on_load,
                        delete_openai_file_objects=ss.delete_openai_file_objects_after_detach,
                        clear_local_knowledge_dir_first=ss.clear_local_knowledge_dir_before_load,
                    )
                    n_files = len(paths)
                finally:
                    conn.close()
            except OpenAIAdminError as e:
                err = str(e)
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as e:
                err = str(e)

            def done() -> None:
                host._end_busy(
                    f"Step 6: loaded {n_files} file(s)." if not err else "Step 6 Load failed."
                )
                if err:
                    host._pipeline_step_clock.pop((sid, 6), None)
                    messagebox.showerror("Step 6 — Load", err, parent=host._root)
                    self._status_var.set(f"Error: {err}")
                else:
                    host._pipeline_step_finish_from_partial(
                        sid,
                        6,
                        agent=False,
                        in_tok=0,
                        out_tok=0,
                        in_usd=0.0,
                        out_usd=0.0,
                        models=f"Load → vector store ({n_files} chunk(s))",
                    )
                    self._status_var.set(f"Uploaded {n_files} chunk(s). Path: {session_knowledge_dir(sid)}")
                self.refresh_vector_status()

            host._root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _on_write(self, extra_angle_context: str | None = None) -> None:
        host = self._host
        if getattr(host, "_busy", False):
            return
        sid = self._sid()
        if not sid:
            messagebox.showinfo("Step 6", "Select a session first.", parent=host._root)
            return
        title = self._title()
        ss = self._gather_settings()
        angle_for_run = (extra_angle_context or "").strip() or None
        try:
            conn = connect(get_db_path())
            try:
                upsert_chat_session(conn, sid, title)
                vid = get_chat_session_openai_vector_store_id(conn, sid)
                if not vid:
                    try:
                        vid = ensure_session_vector_store_in_db(conn, sid, title)
                    except OpenAIAdminError as e:
                        messagebox.showerror(
                            "Step 6",
                            "No vector store is attached to this session yet, and provisioning failed:\n"
                            f"{e}\n\nRun **Load knowledge** first (that always creates a store if missing).",
                            parent=host._root,
                        )
                        return
                rows = conn.execute(
                    "SELECT local_path FROM step6_knowledge_files WHERE chat_session_id = ? ORDER BY chunk_index",
                    (sid,),
                ).fetchall()
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 6", f"Database error: {e}", parent=host._root)
            return
        if not vid:
            messagebox.showwarning(
                "Step 6",
                "Could not resolve a vector store for PARI/file_search.",
                parent=host._root,
            )
            return
        if not rows:
            messagebox.showwarning(
                "Step 6",
                "No knowledge files uploaded. Click Load first.",
                parent=host._root,
            )
            return
        k_paths = [Path(str(r["local_path"])) for r in rows if r["local_path"]]

        if self._top_nb is not None:
            self._top_nb.select(0)

        host._begin_busy("Step 6 — Writing report…", op="step6")
        host._pipeline_step_start(sid, 6)
        self._toc_text.delete("1.0", END)
        self._section_text.delete("1.0", END)
        self._status_var.set("PARI report in progress…")
        cancel = getattr(host, "_cancel_bot_work", None)
        if cancel is not None:
            cancel.clear()

        model = (self._model_var.get() or "").strip() or None

        def queue_toc_delta(d: str) -> None:
            def append() -> None:
                self._toc_text.insert(END, d)
                self._toc_text.see(END)

            host._root.after(0, append)

        def queue_sec_delta(d: str) -> None:
            def append() -> None:
                self._section_text.insert(END, d)
                self._section_text.see(END)

            host._root.after(0, append)

        def queue_status(s: str) -> None:
            host._root.after(0, lambda: self._status_var.set(s))

        def work() -> None:
            err_msg: str | None = None
            index_err: str | None = None
            run_id: int | None = None
            out_dir: Path | None = None
            pari_result = None
            try:
                conn_w = connect(get_db_path())
                try:
                    run_id = insert_step6_report_run(
                        conn_w, chat_session_id=sid, model=model, commit=True
                    )
                    update_step6_report_run(
                        conn_w, run_id, status="running", commit=True
                    )
                finally:
                    conn_w.close()
                conn2 = connect(get_db_path())
                try:
                    result = run_step6_pari_report(
                        conn2,
                        sid,
                        vector_store_id=vid,
                        knowledge_md_paths=k_paths,
                        model=model,
                        settings=ss,
                        cancel_event=cancel,
                        on_toc_delta=queue_toc_delta,
                        on_section_delta=queue_sec_delta,
                        on_status=queue_status,
                        extra_angle_context=angle_for_run,
                    )
                finally:
                    conn2.close()
                if cancel is not None and cancel.is_set():
                    raise RuntimeError("Cancelled")
                pari_result = result
                out = session_reports_dir(sid) / str(run_id)
                paths = write_all_formats(result.markdown, out, title=title or "Report")
                self._paths = {k: v for k, v in paths.items() if v is not None}
                out_dir = out
                conn3 = connect(get_db_path())
                try:
                    update_step6_report_run(
                        conn3,
                        run_id,
                        status="done",
                        report_dir=str(out.resolve()),
                        commit=True,
                    )
                    md_path = paths.get("md")
                    if md_path and md_path.is_file() and run_id is not None:
                        try:
                            index_report_markdown_on_session_vector_store(
                                conn3,
                                sid,
                                title,
                                md_path,
                                run_id,
                                commit=True,
                            )
                        except OpenAIAdminError as e:
                            index_err = str(e)
                finally:
                    conn3.close()
            except RuntimeError as e:
                err_msg = str(e)
                if err_msg == "Cancelled" and run_id is not None:
                    try:
                        c4 = connect(get_db_path())
                        try:
                            update_step6_report_run(
                                c4,
                                run_id,
                                status="cancelled",
                                error_message="Cancelled",
                                commit=True,
                            )
                        finally:
                            c4.close()
                    except (OSError, sqlite3.Error):
                        pass
                elif run_id is not None:
                    try:
                        c4 = connect(get_db_path())
                        try:
                            update_step6_report_run(
                                c4,
                                run_id,
                                status="error",
                                error_message=err_msg,
                                commit=True,
                            )
                        finally:
                            c4.close()
                    except (OSError, sqlite3.Error):
                        pass
            except (OSError, sqlite3.Error) as e:
                err_msg = str(e)
                if run_id is not None:
                    try:
                        c = connect(get_db_path())
                        try:
                            update_step6_report_run(
                                c,
                                run_id,
                                status="error",
                                error_message=err_msg,
                                commit=True,
                            )
                        finally:
                            c.close()
                    except (OSError, sqlite3.Error):
                        pass
            except Exception as e:
                err_msg = str(e)
                if run_id is not None:
                    try:
                        c = connect(get_db_path())
                        try:
                            update_step6_report_run(
                                c,
                                run_id,
                                status="error",
                                error_message=err_msg,
                                commit=True,
                            )
                        finally:
                            c.close()
                    except (OSError, sqlite3.Error):
                        pass

            def done() -> None:
                host._end_busy(
                    "Step 6 report done."
                    if not err_msg
                    else (
                        "Step 6 stopped."
                        if err_msg == "Cancelled"
                        else "Step 6 report failed."
                    )
                )
                if err_msg:
                    host._pipeline_step_clock.pop((sid, 6), None)
                elif pari_result is not None:
                    mname = (pari_result.model or "").strip() or "gpt-4o-mini"
                    cin, cout, _ = split_cost_usd(
                        "openai",
                        mname,
                        prompt_tokens=pari_result.prompt_tokens,
                        completion_tokens=pari_result.completion_tokens,
                    )
                    host._pipeline_step_finish_from_partial(
                        sid,
                        6,
                        agent=True,
                        in_tok=int(pari_result.prompt_tokens),
                        out_tok=int(pari_result.completion_tokens),
                        in_usd=cin,
                        out_usd=cout,
                        models=f"PARI report — {mname}",
                    )
                if err_msg == "Cancelled":
                    self._status_var.set("Cancelled.")
                elif err_msg:
                    messagebox.showerror("Step 6 — Write", err_msg, parent=host._root)
                elif out_dir:
                    msg = f"Saved under {out_dir}"
                    if index_err:
                        msg += f" (vector index warning: {index_err})"
                    self._status_var.set(msg)
                    if index_err:
                        messagebox.showwarning(
                            "Step 6 — Index",
                            "Report files were saved, but indexing report.md on the vector store failed:\n"
                            f"{index_err}",
                            parent=host._root,
                        )
                    if self._paths.get("html"):
                        webbrowser.open(self._paths["html"].as_uri())
                self._refresh_report_runs_list()

            host._root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _latest_paths(self) -> dict[str, Path]:
        sid = self._sid()
        if not sid:
            return {}
        try:
            conn = connect(get_db_path())
            try:
                run = latest_step6_report_run(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            return {}
        if not run or run.status != "done" or not run.report_dir:
            return {}
        base = Path(run.report_dir)
        out: dict[str, Path] = {}
        for name, ext in [("md", ".md"), ("html", ".html"), ("docx", ".docx"), ("pdf", ".pdf")]:
            p = base / f"report{ext}"
            if p.is_file():
                out[name] = p
        return out

    def _download(self, kind: str) -> None:
        host = self._host
        paths = self._paths.get(kind) and {kind: self._paths[kind]} or {}
        if not paths.get(kind):
            paths = self._latest_paths()
        p = paths.get(kind)
        if not p or not p.is_file():
            messagebox.showinfo(
                "Step 6",
                f"No {kind} file available. Run WRITE first.",
                parent=host._root,
            )
            return
        ext = {"md": ".md", "docx": ".docx", "pdf": ".pdf"}[kind]
        dest = filedialog.asksaveasfilename(
            parent=host._root,
            defaultextension=ext,
            initialfile=p.name,
            filetypes=[(kind.upper(), f"*{ext}")],
        )
        if dest:
            try:
                dest_path = Path(dest)
                dest_path.write_bytes(p.read_bytes())
            except OSError as e:
                messagebox.showerror("Step 6", str(e), parent=host._root)

    def _open_html(self) -> None:
        paths = self._paths.get("html") and {"html": self._paths["html"]} or {}
        p = paths.get("html") or self._latest_paths().get("html")
        if p and p.is_file():
            webbrowser.open(p.as_uri())
        else:
            messagebox.showinfo("Step 6", "No HTML report yet.", parent=self._host._root)
