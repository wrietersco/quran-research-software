"""Question refiner chat UI: sessions (left) + conversation + send."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from dataclasses import asdict
import threading
from collections.abc import Callable
from typing import Any
import tkinter as tk
from tkinter import BOTH, END, HORIZONTAL, LEFT, RIGHT, VERTICAL, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from src.chat.bot1_engine import (
    BOT1_TEMPERATURE,
    BOT1_TOOL_PERSISTENCE_SUFFIX,
    Bot1Cancelled,
    Bot1Error,
    Bot1Result,
    clear_bot1_base_instructions_override,
    load_bot1_base_instructions,
    resolve_bot1_model,
    run_bot1,
    save_bot1_base_instructions,
)
from src.chat.bot1_ui_settings import (
    load_bot1_ui_model,
    load_bot1_ui_settings,
    save_bot1_ui_model,
    save_bot1_ui_settings,
)
from src.chat.bot2_engine import (
    Bot2Cancelled,
    Bot2Error,
    Bot2Result,
    bot2_instructions_suffix,
    clear_bot2_base_instructions_override,
    load_bot2_base_instructions,
    resolve_bot2_model,
    run_bot2_synonyms,
    save_bot2_base_instructions,
)
from src.chat.llm_provider import (
    LlmProviderConfig,
    LlmProviderError,
    default_model_for_provider,
    default_shortlist_llm_model,
    resolve_provider_config,
)
from src.chat.llm_pricing import split_cost_usd
from src.chat.openai_documented_models import RESPONSES_TOOL_MODEL_CHOICES
from src.chat.step5_engine import (
    build_verse_manifest,
    clear_step5_base_instructions_override,
    load_step5_base_instructions,
    load_step5_system_prompt,
    manifest_to_json,
    save_step5_base_instructions,
    system_prompt_sha256,
)
from src.chat.step5_orchestrator import Step5Orchestrator
from src.chat.step5_shortlist_logging import shortlist_log_file_path
from src.chat.step5_ui_settings import (
    Step5UiSettings,
    load_step5_ui_settings,
    save_step5_ui_settings,
)
from src.chat.bot2_ui_settings import (
    load_bot2_ui_model,
    load_bot2_ui_settings,
    save_bot2_ui_model,
    save_bot2_ui_settings,
)
from src.chat.refine_engine import (
    REFINE_TEMPERATURE,
    RefineError,
    RefineResult,
    clear_refiner_base_instructions_override,
    extract_refined_json,
    extract_refined_question,
    load_refiner_base_instructions,
    refine_reply,
    save_refiner_base_instructions,
    split_assistant_for_display,
)
from src.chat.session_cleanup import (
    SESSION_DELETE_STEP_LABELS,
    run_session_deletion_desktop,
)
from src.chat.session_vector_store import create_session_vector_store_async
from src.ui.session_delete_progress import SessionDeleteProgressDialog
from src.chat.sessions_store import ChatSessionsStore
from src.config import (  # loads `.env` on first import (see config._load_dotenv)
    PROJECT_ROOT,
    RAW_QURAN_DIR,
    get_db_path,
)

# Step 3 pipeline table: whole-field surah:ayah filter (e.g. "6:40", " 12 : 255 ")
_FV_TABLE_SURAH_AYAH_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


def _parse_fv_table_surah_ayah(q: str) -> tuple[int, int] | None:
    m = _FV_TABLE_SURAH_AYAH_RE.match(q.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))
from src.db.bot2_synonyms import (
    ConnotationWorkItem,
    bot1_connotation_ids_with_bot2_for_bot1_run,
    fetch_latest_bot2_display_lines,
    insert_bot2_synonym_pipeline,
    latest_bot1_pipeline_run_id,
    list_connotations_for_bot1_run,
)
from src.db.find_verses import (
    FindVersesStats,
    Step3FindVersesScorecard,
    compute_step3_find_verses_scorecard,
    fetch_ayah_texts,
    fetch_adhoc_verse_matches_for_session,
    fetch_find_verse_matches_for_session,
    fetch_step4_kalimat_pipeline_rows,
    group_adhoc_rows_by_query,
    run_find_verses_for_session,
    save_adhoc_verse_matches,
    search_arabic_text_in_quran,
)
from src.db.chat_pipeline import (
    fetch_latest_bot1_analysis_dict,
    insert_bot1_step_run,
    refined_question_id_for_session,
    refined_question_text_for_session,
    update_chat_session_title,
    upsert_chat_session,
    upsert_session_refined_question,
)
from src.db.connection import connect
from src.ui.step6_report_tab import Step6ReportPane
from src.db.find_match_words import fetch_token_ids_for_find_match
from src.db.verse_hierarchy import (
    MorphemeRootRow,
    WordMorphemeRoots,
    fetch_ayah_morpheme_roots,
    fetch_lane_lexicon_for_morph_root,
    fetch_morpheme_roots_for_token_ids,
)
from src.db.question_refiner_messages import insert_question_refiner_message
from src.db.step5_synthesis import (
    Step5MatchRow,
    Step5RequestStats,
    Step5RunAnalytics,
    bulk_seed_step5_jobs_for_run,
    fetch_step5_run_models_and_split_cost,
    cancel_step5_run,
    create_step5_run,
    delete_step5_synthesis_for_session,
    fetch_step5_job_llm_detail,
    fetch_step5_progress,
    fetch_step5_request_log_for_run,
    fetch_step5_request_stats,
    fetch_step5_result_detail,
    fetch_step5_results_for_run,
    fetch_step5_run_analytics,
    fetch_step5_shortlist_find_match_ids,
    fetch_step5_shortlist_rows,
    fetch_step5_shortlist_run_meta,
    fetch_step5_shortlist_scores_map,
    insert_step5_manifest,
    insert_step5_run_stats_snapshot,
    latest_step5_run_id_for_session,
    list_step5_matches_for_session,
    replace_step5_session_shortlist,
    reset_stale_step5_in_progress_jobs,
    step5_run_is_resumable,
)
from src.ui.app_icons import AppIconSet
from src.ui.arabic_display import shape_arabic_display
from src.ui.lexicon_display import entry_dialog_title, heading_display_label
from src.ui.material_theme import (
    MaterialColors,
    style_mpl_figure,
    style_tk_listbox,
    style_tk_text_composer_input,
    style_tk_text_input,
    style_tk_text_readonly,
)
from src.ui.step5_llm_response_view import apply_step5_response_to_tk_text, build_step5_llm_response_html
from src.ui.pipeline_summary import PipelineSummaryPane, StepPipelineMetric

_STEP5_DEEPSEEK_MODEL_CHOICES: tuple[str, ...] = (
    "deepseek-v3.2",
    "deepseek-chat",
    "deepseek-reasoner",
)

_STEP5_OPENROUTER_MODEL_CHOICES: tuple[str, ...] = (
    "deepseek/deepseek-v3.2",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
)


def _session_delete_confirmation_text(session_id: str) -> str:
    """Multi-line warning for session delete: same steps as the progress dialog (session_cleanup)."""
    sid_short = session_id[:8] + "…" if len(session_id) > 12 else session_id
    bullets = "\n".join(f"• {lab}" for lab in SESSION_DELETE_STEP_LABELS)
    return (
        "Deleting this session cannot be undone.\n\n"
        "The following will be removed (each step is shown in the progress window):\n\n"
        f"{bullets}\n\n"
        "Remote OpenAI cleanup is attempted but may not complete if the network or API fails.\n\n"
        f"Session: {sid_short}\n\n"
        "Delete this session now?"
    )


class QuestionRefinerTab:
    def __init__(
        self,
        parent: ttk.Frame,
        root: tk.Tk,
        *,
        arabic_font: str,
        latin_font: str,
        icon_set: AppIconSet | None = None,
        on_lexicon_definition: Callable[[str, str], None] | None = None,
    ) -> None:
        self._root = root
        self._on_lexicon_definition = on_lexicon_definition
        self._arabic = arabic_font
        self._latin = latin_font
        self._icons = icon_set or AppIconSet(root)
        self._store = ChatSessionsStore(
            PROJECT_ROOT / "data" / "chat" / "question_refiner_sessions.json"
        )
        self._current_id: str | None = None
        self._session_step_banner_var = tk.StringVar(value="")
        self._refined_question_banner_var = tk.StringVar(value="")
        self._last_result_by_session: dict[str, RefineResult] = {}
        self._session_totals: dict[str, dict[str, int]] = {}
        self._app_totals = {"requests": 0, "prompt": 0, "completion": 0, "total": 0}
        self._sys_prompt_chars: int | None = None
        self._last_bot1_error_by_session: dict[str, str] = {}
        self._last_bot2_error_by_session: dict[str, str] = {}
        self._busy = False
        self._busy_op: str | None = None
        self._cancel_bot_work = threading.Event()
        self._adhoc_search_hits: list[tuple[int, int]] = []
        self._adhoc_search_query: str = ""
        self._fv_adhoc_session: str | None = None
        # sid -> (not_found_connotations, not_found_synonyms) from last «Run Find Verses & save»
        self._fv_pipeline_not_found_by_session: dict[
            str,
            tuple[
                tuple[tuple[int, str], ...],
                tuple[tuple[int, int, str], ...],
            ],
        ] = {}
        # Full Step 3 table rows for client-side search (values tuple + treeview tags)
        self._fv_pipeline_row_cache: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self._step5_orchestrator: Step5Orchestrator | None = None
        self._step5_poll_after_id: str | None = None
        self._step5_live_refresh_after_id: str | None = None
        self._bot2_refresh_after_id: str | None = None
        self._step5_run_id_by_session: dict[str, int] = {}
        self._pipeline_metrics: dict[str, dict[int, StepPipelineMetric]] = {}
        self._pipeline_step_clock: dict[tuple[str, int], tuple[float, datetime]] = {}

        outer = ttk.Frame(parent, padding=(10, 8, 10, 10))
        outer.pack(fill=BOTH, expand=True)

        qr_scroll = tk.Canvas(
            outer,
            highlightthickness=0,
            bd=0,
            bg=MaterialColors.surface_dim,
        )
        qr_vsb = ttk.Scrollbar(outer, orient=VERTICAL, command=qr_scroll.yview)
        qr_scroll.configure(yscrollcommand=qr_vsb.set)
        scroll_inner = ttk.Frame(qr_scroll)
        qr_win = qr_scroll.create_window((0, 0), window=scroll_inner, anchor="nw")

        def _qr_sync_inner_width(event: tk.Event) -> None:
            qr_scroll.itemconfigure(qr_win, width=event.width)

        def _qr_sync_scrollregion(_event: tk.Event | None = None) -> None:
            qr_scroll.update_idletasks()
            box = qr_scroll.bbox("all")
            if box:
                qr_scroll.configure(scrollregion=box)

        qr_scroll.bind("<Configure>", _qr_sync_inner_width)
        scroll_inner.bind("<Configure>", _qr_sync_scrollregion)

        qr_vsb.pack(side=RIGHT, fill="y")
        qr_scroll.pack(side=LEFT, fill=BOTH, expand=True)
        self._qr_scroll_canvas = qr_scroll
        self._qr_sync_scrollregion = _qr_sync_scrollregion

        self._prog_fr = ttk.Frame(scroll_inner)
        self._request_progress = ttk.Progressbar(
            self._prog_fr, mode="indeterminate", maximum=100
        )
        self._request_progress.pack(fill="x")

        self._pipeline_banner = ttk.Frame(
            scroll_inner, style="PipelineBanner.TFrame", padding=(12, 10)
        )
        self._pipeline_banner.pack(fill="x", pady=(0, 6))
        ttk.Label(
            self._pipeline_banner,
            text="Analysis pipeline",
            style="PipelineBannerTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            self._pipeline_banner,
            text=(
                "Each tab is one stage. Start on Refine, then go 1 → 6 in order when you are ready. "
                "Summary is optional — open it anytime for a bird’s-eye view."
            ),
            style="PipelineBannerBody.TLabel",
            wraplength=960,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self._sub_notebook = ttk.Notebook(scroll_inner, style="Pipeline.TNotebook")
        self._sub_notebook.pack(fill=BOTH, expand=True)

        tab_refiner = ttk.Frame(self._sub_notebook)
        tab_bot1 = ttk.Frame(self._sub_notebook)
        tab_bot2 = ttk.Frame(self._sub_notebook)
        tab_find_verses = ttk.Frame(self._sub_notebook)
        self._tab_step4 = ttk.Frame(self._sub_notebook)
        self._tab_step5 = ttk.Frame(self._sub_notebook)
        self._tab_step6 = ttk.Frame(self._sub_notebook)
        self._sub_notebook.add(tab_refiner, text="Refine")
        self._sub_notebook.add(tab_bot1, text="1 · Bot 1")
        self._sub_notebook.add(tab_bot2, text="2 · Bot 2")
        self._sub_notebook.add(tab_find_verses, text="3 · Verses")
        self._sub_notebook.add(self._tab_step4, text="4 · Kalimat")
        self._sub_notebook.add(self._tab_step5, text="5 · Shortlist + synth")
        self._sub_notebook.add(self._tab_step6, text="6 · Report")
        self._tab_summary = ttk.Frame(self._sub_notebook)
        self._sub_notebook.add(self._tab_summary, text="Summary")
        self._step6_pane = Step6ReportPane(self, self._tab_step6)
        self._summary_pane = PipelineSummaryPane(self, self._tab_summary, latin_font=latin_font)

        def _on_sub_notebook_tab_change(_event: tk.Event | None = None) -> None:
            self._root.after_idle(_qr_sync_scrollregion)
            try:
                if str(self._sub_notebook.select()) == str(self._tab_step4):
                    self._refresh_step4_tab()
                elif str(self._sub_notebook.select()) == str(self._tab_step5):
                    self._refresh_step5_tab()
                elif str(self._sub_notebook.select()) == str(self._tab_step6):
                    self._step6_pane.refresh_vector_status()
                elif str(self._sub_notebook.select()) == str(self._tab_summary):
                    self._refresh_pipeline_summary_tab()
            except tk.TclError:
                pass

        self._sub_notebook.bind("<<NotebookTabChanged>>", _on_sub_notebook_tab_change)

        self._pack_question_refiner_header(tab_refiner)

        paned = ttk.PanedWindow(tab_refiner, orient=tk.HORIZONTAL)
        paned.pack(fill=BOTH, expand=True, padx=(12, 12), pady=(0, 10))

        left_wrap = tk.Frame(paned, bg=MaterialColors.surface, highlightthickness=0)
        left_card = tk.Frame(
            left_wrap,
            bg=MaterialColors.surface_container,
            highlightthickness=1,
            highlightbackground=MaterialColors.chat_shell_border,
        )
        left_card.pack(fill=BOTH, expand=True)
        left = ttk.Frame(left_card, style="Card.TFrame", width=240, padding=(14, 14))
        left.pack(fill=BOTH, expand=True)
        paned.add(left_wrap, weight=0)

        sess_hdr = ttk.Frame(left, style="Card.TFrame")
        sess_hdr.pack(anchor="w", fill="x", pady=(0, 8))
        ic = self._icons.get("chat")
        if ic:
            ttk.Label(sess_hdr, image=ic, style="SectionHeading.TLabel").pack(
                side="left", padx=(0, 8)
            )
        ttk.Label(sess_hdr, text="Your sessions", style="SectionHeading.TLabel").pack(
            side="left"
        )

        btns = ttk.Frame(left, style="Card.TFrame")
        btns.pack(fill="x", pady=(0, 8))
        a_i, e_i, d_i = self._icons.get("add"), self._icons.get("edit"), self._icons.get("delete")

        def _mb(**kw: Any) -> ttk.Button:
            kw.setdefault("style", "SessionTool.TButton")
            return ttk.Button(btns, **kw)

        nk: dict = {"text": "New", "command": self._new_session}
        if a_i:
            nk["image"] = a_i
            nk["compound"] = "left"
        _mb(**nk).pack(fill="x", pady=(0, 4))
        rk: dict = {"text": "Rename", "command": self._rename_session}
        if e_i:
            rk["image"] = e_i
            rk["compound"] = "left"
        _mb(**rk).pack(fill="x", pady=(0, 4))
        dk: dict = {"text": "Delete", "command": self._delete_session}
        if d_i:
            dk["image"] = d_i
            dk["compound"] = "left"
        _mb(**dk).pack(fill="x")

        ttk.Label(
            left,
            text="Pick a thread or start a new one. Each session keeps its own refined question and pipeline data.",
            style="Hint.TLabel",
            wraplength=220,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        list_fr = tk.Frame(
            left,
            bg=MaterialColors.composer_trough,
            highlightthickness=1,
            highlightbackground=MaterialColors.chat_shell_border,
        )
        list_fr.pack(fill=BOTH, expand=True)
        self._session_list = tk.Listbox(
            list_fr,
            width=26,
            height=10,
            font=(latin_font, 10),
            selectmode=tk.SINGLE,
            activestyle="none",
        )
        style_tk_listbox(self._session_list, latin_family=latin_font, size=10)
        sb_l = ttk.Scrollbar(list_fr, orient=VERTICAL, command=self._session_list.yview)
        self._session_list.configure(yscrollcommand=sb_l.set)
        self._session_list.pack(side=LEFT, fill=BOTH, expand=True)
        sb_l.pack(side=RIGHT, fill="y")

        self._session_list.bind("<<ListboxSelect>>", self._on_list_select)

        center = ttk.Frame(paned, style="Card.TFrame", padding=(18, 14))
        paned.add(center, weight=1)

        has_key = bool((os.environ.get("OPENAI_API_KEY") or "").strip())
        intro = ttk.Label(
            center,
            wraplength=640,
            justify="left",
            style="ChatIntro.TLabel",
            text=(
                "Chat with the refiner: say what you are exploring in your own words. "
                "It helps you converge on one clear question, then you move to tab 1."
            ),
        )
        intro.grid(row=0, column=0, sticky="nw", pady=(0, 6))
        if not has_key:
            ttk.Label(
                center,
                text="Set OPENAI_API_KEY in .env (or your environment) and restart the app.",
                wraplength=640,
                justify="left",
                style="ErrorHint.TLabel",
            ).grid(row=1, column=0, sticky="nw", pady=(0, 10))
            _intro_rows = 2
        else:
            _intro_rows = 1

        _log_row = _intro_rows
        log_fr = ttk.Frame(center, style="Card.TFrame")
        log_fr.grid(row=_log_row, column=0, sticky="new", pady=(0, 10))
        ttk.Label(log_fr, text="Messages", style="ChatSection.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        self._refine_chat_shell = tk.Frame(
            log_fr,
            height=340,
            highlightthickness=1,
            highlightbackground=MaterialColors.chat_shell_border,
            bg=MaterialColors.composer_trough,
        )
        self._refine_chat_shell.pack(fill=tk.X, expand=False)
        self._refine_chat_shell.pack_propagate(False)
        log_row = tk.Frame(self._refine_chat_shell, bg=MaterialColors.surface_container)
        log_row.pack(fill=BOTH, expand=True, padx=3, pady=3)
        self._log = tk.Text(
            log_row,
            wrap="word",
            state="disabled",
            font=(arabic_font, 11),
            relief="flat",
        )
        style_tk_text_readonly(
            self._log, family=arabic_font, size=11, soft_border=True
        )
        vsb = ttk.Scrollbar(log_row, orient=VERTICAL, command=self._log.yview)
        self._log.configure(yscrollcommand=vsb.set)
        self._log.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill="y")

        self._log.tag_configure(
            "h_user",
            font=(latin_font, 10, "bold"),
            foreground=MaterialColors.secondary,
        )
        self._log.tag_configure(
            "h_bot",
            font=(latin_font, 10, "bold"),
            foreground=MaterialColors.success,
        )
        self._log.tag_configure(
            "refined",
            font=(arabic_font, 11, "italic"),
            foreground=MaterialColors.tertiary,
        )
        self._log.tag_configure("err", font=(latin_font, 10), foreground=MaterialColors.error)

        _inp_row = _log_row + 1
        inp_fr = ttk.Frame(center, style="Card.TFrame")
        inp_fr.grid(row=_inp_row, column=0, sticky="ew", pady=(0, 6))
        composer = tk.Frame(
            inp_fr,
            bg=MaterialColors.composer_trough,
            highlightthickness=1,
            highlightbackground=MaterialColors.chat_shell_border,
        )
        composer.pack(fill=tk.X, expand=False)
        inp_row = tk.Frame(composer, bg=MaterialColors.composer_trough)
        inp_row.pack(fill=tk.X, padx=4, pady=4)
        self._input = ScrolledText(
            inp_row,
            height=3,
            width=40,
            wrap="word",
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
        )
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        for child in self._input.winfo_children():
            if isinstance(child, tk.Text):
                style_tk_text_composer_input(child, family=arabic_font, size=11)
                child.configure(font=(arabic_font, 11))
        self._input.configure(bg=MaterialColors.composer_trough)
        s_img = self._icons.get("send")
        sk: dict = {"text": "Send", "command": self._send, "style": "Accent.TButton"}
        if s_img:
            sk["image"] = s_img
            sk["compound"] = "left"
        self._send_btn = ttk.Button(inp_row, **sk)
        self._send_btn.pack(side=tk.RIGHT, anchor="se", padx=(0, 2), pady=(0, 2))

        _stat_row = _inp_row + 1
        self._status = tk.StringVar(value="Ready." if has_key else "API key missing.")
        ttk.Label(center, textvariable=self._status, style="Status.TLabel").grid(
            row=_stat_row, column=0, sticky="nw", pady=(0, 4)
        )
        ttk.Label(
            center,
            text="Tip: Ctrl+Enter sends. Model instructions and token details are under Advanced — you rarely need them.",
            style="Hint.TLabel",
            wraplength=640,
            justify="left",
        ).grid(row=_stat_row + 1, column=0, sticky="nw", pady=(0, 8))

        _adv_toggle_row = _stat_row + 2
        adv_toggle_shell = ttk.Frame(center, style="Card.TFrame")
        adv_toggle_shell.grid(row=_adv_toggle_row, column=0, sticky="ew", pady=(4, 0))
        self._qr_advanced_open = False
        self._qr_adv_toggle_btn = ttk.Button(
            adv_toggle_shell,
            text="Advanced — model instructions & LLM diagnostics ▼",
            command=self._toggle_qr_advanced_panel,
            style="Disclosure.TButton",
        )
        self._qr_adv_toggle_btn.pack(anchor="w")

        self._qr_adv_body = ttk.Frame(center, style="Card.TFrame")
        self._qr_adv_grid_row = _adv_toggle_row + 1

        ttk.Label(
            self._qr_adv_body,
            text="Model instructions (system prompt)",
            style="SectionHeading.TLabel",
        ).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self._qr_adv_body,
            wraplength=620,
            justify="left",
            style="Hint.TLabel",
            text=(
                "Sent as the Chat Completions system message. Save edits to "
                "data/chat/refiner_system_base.txt. Send uses the text below; do not leave it empty after Reload."
            ),
        ).pack(anchor="w", pady=(0, 8))

        ref_lf = ttk.Labelframe(
            self._qr_adv_body,
            text="Editor",
            style="Card.TLabelframe",
            padding=(10, 8),
        )
        ref_lf.pack(fill="x", pady=(0, 12))
        ref_btn = ttk.Frame(ref_lf, style="Card.TFrame")
        ref_btn.pack(fill="x", pady=(0, 6))
        ttk.Button(
            ref_btn,
            text="Save to disk",
            command=self._save_refiner_system_core,
        ).pack(side=tk.LEFT)
        ttk.Button(
            ref_btn,
            text="Reset to default",
            command=self._reset_refiner_system_core,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            ref_btn,
            text="Reload",
            command=self._reload_refiner_system_core,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ref_core_fr = ttk.Frame(ref_lf, style="Card.TFrame")
        ref_core_fr.pack(fill="both", expand=True)
        self._refiner_sys_core = tk.Text(
            ref_core_fr,
            height=6,
            wrap="word",
            relief="flat",
            font=("Consolas", 9),
        )
        style_tk_text_input(self._refiner_sys_core, family=latin_font, size=9)
        self._refiner_sys_core.configure(font=("Consolas", 9))
        ref_sb = ttk.Scrollbar(
            ref_core_fr, orient=VERTICAL, command=self._refiner_sys_core.yview
        )
        self._refiner_sys_core.configure(yscrollcommand=ref_sb.set)
        self._refiner_sys_core.pack(side=LEFT, fill=BOTH, expand=True)
        ref_sb.pack(side=RIGHT, fill="y")
        try:
            _ref_core = load_refiner_base_instructions()
        except RefineError as e:
            _ref_core = f"(Could not load: {e})"
        self._refiner_sys_core.insert("1.0", _ref_core)

        ttk.Separator(self._qr_adv_body, orient=tk.HORIZONTAL).pack(
            fill="x", pady=(4, 12)
        )
        dh = ttk.Frame(self._qr_adv_body, style="Card.TFrame")
        dh.pack(anchor="w", fill="x", pady=(0, 8))
        bi = self._icons.get("bar_chart")
        if bi:
            ttk.Label(dh, image=bi, style="SectionHeading.TLabel").pack(
                side="left", padx=(0, 8)
            )
        ttk.Label(
            dh,
            text="LLM diagnostics",
            style="SectionHeading.TLabel",
        ).pack(side="left")
        ttk.Label(dh, text="tokens · model · costs", style="Hint.TLabel").pack(
            side="left", padx=(8, 0)
        )
        diag_body = ttk.Frame(self._qr_adv_body, style="Card.TFrame")
        diag_body.pack(fill=BOTH, expand=True)
        self._diag_text = tk.Text(
            diag_body,
            height=14,
            width=72,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        style_tk_text_readonly(
            self._diag_text, family=latin_font, size=9, monospace=True, subtle=True
        )
        dsb = ttk.Scrollbar(diag_body, orient=VERTICAL, command=self._diag_text.yview)
        self._diag_text.configure(yscrollcommand=dsb.set)
        self._diag_text.pack(side=LEFT, fill=BOTH, expand=True)
        dsb.pack(side=RIGHT, fill="y")

        center.columnconfigure(0, weight=1)
        _spacer_row = _adv_toggle_row + 2
        center.rowconfigure(_spacer_row, weight=1)

        def _refine_tab_configure(event: tk.Event) -> None:
            if event.widget != tab_refiner or getattr(event, "height", 0) < 120:
                return
            reserve = 360
            avail = max(240, int(event.height) - reserve)
            nh = min(460, max(260, int(avail * 0.5)))
            try:
                if self._refine_chat_shell.winfo_height() == nh:
                    return
                self._refine_chat_shell.configure(height=nh)
            except tk.TclError:
                pass

        tab_refiner.bind("<Configure>", _refine_tab_configure, add=True)

        def _ctrl_ret(_e: tk.Event) -> str:
            self._send()
            return "break"

        self._input.bind("<Control-Return>", _ctrl_ret)
        for child in self._input.winfo_children():
            if isinstance(child, tk.Text):
                child.bind("<Control-Return>", _ctrl_ret)

        self._build_bot1_tab(tab_bot1)
        self._build_bot2_tab(tab_bot2)
        self._build_find_verses_tab(tab_find_verses)
        self._build_step4_kalimat_tab(self._tab_step4)
        self._build_step5_tab(self._tab_step5)

        self._refresh_list(select_first=True)
        self._sync_diagnostics()
        self._refresh_bot_dependent_tabs()
        self._root.after_idle(_qr_sync_scrollregion)

    def _pack_question_refiner_header(self, tab: ttk.Frame) -> None:
        """Hero strip + session context for the Question refiner tab only."""
        outer = tk.Frame(tab, bg=MaterialColors.surface, highlightthickness=0)
        outer.pack(fill="x", padx=12, pady=(10, 6))
        hero_bar = tk.Frame(outer, bg=MaterialColors.primary_container, highlightthickness=0)
        hero_bar.pack(fill="x")
        accent = tk.Frame(hero_bar, bg=MaterialColors.primary, width=5)
        accent.pack(side=LEFT, fill="y")
        hero = ttk.Frame(hero_bar, style="Hero.TFrame", padding=(16, 14))
        hero.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(hero, text="Refine your question", style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(
            hero,
            textvariable=self._session_step_banner_var,
            style="HeroMeta.TLabel",
        ).pack(anchor="w", pady=(10, 0))
        rq = ttk.Label(
            hero,
            textvariable=self._refined_question_banner_var,
            style="HeroRq.TLabel",
            wraplength=920,
            justify="left",
        )
        rq.pack(anchor="w", pady=(8, 0))
        rq.configure(font=(self._arabic, 11))

    def _toggle_qr_advanced_panel(self) -> None:
        """Show or hide system prompt + diagnostics (progressive disclosure)."""
        self._qr_advanced_open = not self._qr_advanced_open
        if self._qr_advanced_open:
            self._qr_adv_body.grid(
                row=self._qr_adv_grid_row,
                column=0,
                sticky="ew",
                pady=(8, 0),
            )
            self._qr_adv_toggle_btn.configure(
                text="Advanced — model instructions & LLM diagnostics ▲"
            )
        else:
            self._qr_adv_body.grid_remove()
            self._qr_adv_toggle_btn.configure(
                text="Advanced — model instructions & LLM diagnostics ▼"
            )
        self._root.after_idle(self._qr_sync_scrollregion)

    def _sync_session_step_banner(self) -> None:
        """Keep session title and refined question in sync under each step’s main heading."""
        sid = self._current_id
        if not sid:
            self._session_step_banner_var.set("Session: (none selected)")
            self._refined_question_banner_var.set("")
            return
        sess = self._store.get(sid)
        title = (sess.title if sess else sid[:8]).strip() or sid[:8]
        self._session_step_banner_var.set(f"Session: «{title}»")

        rq_text: str | None = None
        try:
            conn = connect(get_db_path())
            try:
                rq_text = refined_question_text_for_session(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            pass
        if not (rq_text or "").strip() and sess:
            for m in reversed(sess.messages):
                if m.role == "assistant":
                    j = extract_refined_json(m.content)
                    if j is not None:
                        q = j.get("question")
                        rq_text = str(q).strip() if q is not None else None
                    else:
                        rq_text = extract_refined_question(m.content)
                    if rq_text and rq_text.strip():
                        break
        rq_clean = (rq_text or "").strip()
        if rq_clean:
            self._refined_question_banner_var.set(f"Refined question: {rq_clean}")
        else:
            self._refined_question_banner_var.set(
                "Refined question: (not set yet — finish chatting on Refine, then run tab 1 · Bot 1)"
            )

    def _pack_step_main_heading(self, tab: ttk.Frame, heading_text: str) -> None:
        lf = self._latin
        hdr = ttk.Frame(tab)
        hdr.pack(anchor="w", fill="x", padx=6, pady=(4, 8))
        ttk.Label(
            hdr,
            text=heading_text,
            font=(lf, 14, "bold"),
            foreground=MaterialColors.primary,
        ).pack(anchor="w")
        ttk.Label(
            hdr,
            textvariable=self._session_step_banner_var,
            font=(lf, 10),
            foreground=MaterialColors.on_surface_variant,
        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(
            hdr,
            textvariable=self._refined_question_banner_var,
            font=(self._arabic, 10),
            foreground=MaterialColors.on_surface,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def _build_bot1_tab(self, tab: ttk.Frame) -> None:
        lf = self._latin
        self._pack_step_main_heading(tab, "Step 1 — Bot 1")
        intro = ttk.Label(
            tab,
            wraplength=760,
            justify="left",
            font=(lf, 10),
            text=(
                "Topics & connotations for this session (see docs/quran-openai-prompts.md). "
                "It reads the latest <<<REFINED_JSON>>> {\"question\": \"…\"} from the "
                "Question refiner chat for the current session, calls the OpenAI Responses API with the "
                "save_topics_connotations_analysis tool (and optional file_search), then stores rows in "
                "pipeline_step_runs, bot1_topics, and bot1_connotations (linked to chat_sessions and the "
                "single finalized question in session_refined_questions)."
            ),
        )
        intro.pack(anchor="w", pady=(0, 6), padx=6)

        sys_lf = ttk.Labelframe(
            tab,
            text="System instructions (Responses API `instructions`)",
            padding=(8, 6),
        )
        sys_lf.pack(fill="both", expand=False, padx=6, pady=(0, 8))
        ttk.Label(
            sys_lf,
            wraplength=740,
            justify="left",
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
            text=(
                "The model receives the editable core below plus the fixed persistence block "
                "(read-only) that tells it to call save_topics_connotations_analysis. "
                "«Save core to disk» writes the core to data/chat/bot1_system_base.txt; "
                "«Run Bot 1» uses the current editor text (saved or not)."
            ),
        ).pack(anchor="w", pady=(0, 6))
        sys_btn = ttk.Frame(sys_lf)
        sys_btn.pack(fill="x", pady=(0, 4))
        ttk.Button(
            sys_btn,
            text="Save core to disk",
            command=self._save_bot1_system_core,
            width=18,
        ).pack(side=tk.LEFT)
        ttk.Button(
            sys_btn,
            text="Reset core to built-in doc",
            command=self._reset_bot1_system_core,
            width=22,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            sys_btn,
            text="Reload core from disk / doc",
            command=self._reload_bot1_system_core,
            width=24,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(sys_lf, text="Core (editable):", font=(lf, 9)).pack(anchor="w")
        core_fr = ttk.Frame(sys_lf)
        core_fr.pack(fill="both", expand=True, pady=(2, 6))
        self._bot1_sys_core = tk.Text(
            core_fr,
            height=9,
            wrap="word",
            relief="flat",
            font=("Consolas", 9),
        )
        sb_core = ttk.Scrollbar(
            core_fr, orient=VERTICAL, command=self._bot1_sys_core.yview
        )
        self._bot1_sys_core.configure(yscrollcommand=sb_core.set)
        self._bot1_sys_core.pack(side=LEFT, fill=BOTH, expand=True)
        sb_core.pack(side=RIGHT, fill="y")
        try:
            _b1_core = load_bot1_base_instructions()
        except Bot1Error as e:
            _b1_core = f"(Could not load built-in instructions: {e})"
        self._bot1_sys_core.insert("1.0", _b1_core)
        ttk.Label(
            sys_lf,
            text="Appended automatically on every run (read-only):",
            font=(lf, 9),
        ).pack(anchor="w")
        pers_fr = ttk.Frame(sys_lf)
        pers_fr.pack(fill="x", pady=(2, 0))
        self._bot1_sys_persist = tk.Text(
            pers_fr,
            height=4,
            wrap="word",
            state="disabled",
            relief="flat",
            font=("Consolas", 9),
        )
        style_tk_text_readonly(
            self._bot1_sys_persist, family="Consolas", size=9, monospace=True
        )
        self._bot1_sys_persist.configure(state="normal")
        self._bot1_sys_persist.insert(
            "1.0", BOT1_TOOL_PERSISTENCE_SUFFIX.lstrip("\n")
        )
        self._bot1_sys_persist.configure(state="disabled")
        sb_p = ttk.Scrollbar(
            pers_fr, orient=VERTICAL, command=self._bot1_sys_persist.yview
        )
        self._bot1_sys_persist.configure(yscrollcommand=sb_p.set)
        self._bot1_sys_persist.pack(side=LEFT, fill="x", expand=True)
        sb_p.pack(side=RIGHT, fill="y")

        model_row = ttk.Frame(tab)
        model_row.pack(fill="x", padx=6, pady=(2, 2))
        ttk.Label(model_row, text="Model id (Chat / Responses API):", font=(lf, 9)).pack(
            side=tk.LEFT
        )
        self._bot1_model_var = tk.StringVar(value=load_bot1_ui_model())
        self._bot1_model_effective = tk.StringVar(value="")
        self._bot1_model_combo = ttk.Combobox(
            model_row,
            textvariable=self._bot1_model_var,
            width=36,
            values=RESPONSES_TOOL_MODEL_CHOICES,
        )
        self._bot1_model_combo.pack(side=tk.LEFT, padx=(8, 0))
        self._bot1_model_combo.bind("<FocusOut>", self._on_bot1_model_focus_out)
        self._bot1_model_var.trace_add("write", self._on_bot1_model_var_write)

        ttk.Label(
            tab,
            textvariable=self._bot1_model_effective,
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
        ).pack(anchor="w", padx=6)
        ttk.Label(
            tab,
            text=(
                "Same model string as in the Responses API `model` field. "
                "Leave blank to use OPENAI_MODEL_BOT1, then OPENAI_MODEL from .env "
                f"(fallback {resolve_bot1_model('')!r})."
            ),
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=6, pady=(0, 2))

        temp_row = ttk.Frame(tab)
        temp_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(temp_row, text="Temperature (optional):", font=(lf, 9)).pack(side=tk.LEFT)
        b1 = load_bot1_ui_settings()
        self._bot1_temp_var = tk.StringVar(
            value="" if b1.temperature is None else str(b1.temperature)
        )
        te = ttk.Entry(temp_row, textvariable=self._bot1_temp_var, width=8)
        te.pack(side=tk.LEFT, padx=(8, 12))
        te.bind("<FocusOut>", self._on_bot1_temperature_focus_out)
        ttk.Label(
            temp_row,
            text=(
                f"empty → {BOT1_TEMPERATURE}; omitted for o-series / gpt-5 "
                "(see bot1_engine.model_allows_temperature)."
            ),
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
        ).pack(side=tk.LEFT)

        self._bot1_status = tk.StringVar(value="")
        self._sync_bot1_effective_model()
        ttk.Label(tab, textvariable=self._bot1_status, font=(lf, 9)).pack(
            anchor="w", pady=(6, 4), padx=6
        )

        btn_fr = ttk.Frame(tab)
        btn_fr.pack(fill="x", pady=(4, 8), padx=6)
        st_img = self._icons.get("smart_toy")
        rk1: dict = {
            "text": "Run Bot 1 & save to DB",
            "command": self._run_bot1_pipeline,
            "width": 26,
        }
        if st_img:
            rk1["image"] = st_img
            rk1["compound"] = "left"
        self._bot1_run_btn = ttk.Button(btn_fr, **rk1)
        self._bot1_run_btn.pack(side=tk.LEFT)
        self._bot1_stop_btn = ttk.Button(
            btn_fr,
            text="Stop Bot 1",
            command=self._request_stop_bot1,
            width=14,
            state="disabled",
        )
        self._bot1_stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._bot1_copy_err_btn = ttk.Button(
            btn_fr,
            text="Copy last Bot 1 error",
            command=self._copy_bot1_error_to_clipboard,
            width=22,
            state="disabled",
        )
        self._bot1_copy_err_btn.pack(side=tk.LEFT, padx=(12, 0))

        out_fr = ttk.Frame(tab)
        out_fr.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))
        self._bot1_preview = tk.Text(
            out_fr,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        style_tk_text_readonly(
            self._bot1_preview, family=lf, size=10, monospace=True
        )
        self._bot1_preview.configure(font=("Consolas", 10))
        sb = ttk.Scrollbar(out_fr, orient=VERTICAL, command=self._bot1_preview.yview)
        self._bot1_preview.configure(yscrollcommand=sb.set)
        self._bot1_preview.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill="y")

    def _on_bot1_temperature_focus_out(self, _event: tk.Event | None = None) -> None:
        raw = self._bot1_temp_var.get().strip()
        ui = load_bot1_ui_settings()
        if not raw:
            ui.temperature = None
        else:
            try:
                ui.temperature = float(raw)
            except ValueError:
                ui.temperature = None
                self._bot1_temp_var.set("")
        save_bot1_ui_settings(ui)

    def _save_bot1_system_core(self) -> None:
        if not hasattr(self, "_bot1_sys_core"):
            return
        raw = self._bot1_sys_core.get("1.0", END).strip()
        try:
            save_bot1_base_instructions(raw)
        except ValueError as e:
            messagebox.showwarning("Bot 1", str(e), parent=self._root)
            return
        messagebox.showinfo(
            "Bot 1",
            "Core instructions saved to data/chat/bot1_system_base.txt.",
            parent=self._root,
        )

    def _reset_bot1_system_core(self) -> None:
        if not hasattr(self, "_bot1_sys_core"):
            return
        clear_bot1_base_instructions_override()
        try:
            body = load_bot1_base_instructions()
        except Bot1Error as e:
            messagebox.showerror("Bot 1", str(e), parent=self._root)
            return
        self._bot1_sys_core.delete("1.0", END)
        self._bot1_sys_core.insert("1.0", body)

    def _reload_bot1_system_core(self) -> None:
        if not hasattr(self, "_bot1_sys_core"):
            return
        try:
            body = load_bot1_base_instructions()
        except Bot1Error as e:
            messagebox.showerror("Bot 1", str(e), parent=self._root)
            return
        self._bot1_sys_core.delete("1.0", END)
        self._bot1_sys_core.insert("1.0", body)

    def _sync_bot2_system_suffix_preview(self, *_args: object) -> None:
        if not hasattr(self, "_bot2_sys_suffix"):
            return
        try:
            n = int(self._bot2_max_syn_var.get().strip() or "8")
        except ValueError:
            n = 8
        text = bot2_instructions_suffix(n).lstrip("\n")
        self._bot2_sys_suffix.configure(state="normal")
        self._bot2_sys_suffix.delete("1.0", END)
        self._bot2_sys_suffix.insert("1.0", text)
        self._bot2_sys_suffix.configure(state="disabled")

    def _save_bot2_system_core(self) -> None:
        if not hasattr(self, "_bot2_sys_core"):
            return
        raw = self._bot2_sys_core.get("1.0", END).strip()
        try:
            save_bot2_base_instructions(raw)
        except ValueError as e:
            messagebox.showwarning("Bot 2", str(e), parent=self._root)
            return
        messagebox.showinfo(
            "Bot 2",
            "Core instructions saved to data/chat/bot2_system_base.txt.",
            parent=self._root,
        )

    def _reset_bot2_system_core(self) -> None:
        if not hasattr(self, "_bot2_sys_core"):
            return
        clear_bot2_base_instructions_override()
        try:
            body = load_bot2_base_instructions()
        except Bot2Error as e:
            messagebox.showerror("Bot 2", str(e), parent=self._root)
            return
        self._bot2_sys_core.delete("1.0", END)
        self._bot2_sys_core.insert("1.0", body)

    def _reload_bot2_system_core(self) -> None:
        if not hasattr(self, "_bot2_sys_core"):
            return
        try:
            body = load_bot2_base_instructions()
        except Bot2Error as e:
            messagebox.showerror("Bot 2", str(e), parent=self._root)
            return
        self._bot2_sys_core.delete("1.0", END)
        self._bot2_sys_core.insert("1.0", body)

    def _save_refiner_system_core(self) -> None:
        if not hasattr(self, "_refiner_sys_core"):
            return
        raw = self._refiner_sys_core.get("1.0", END).strip()
        try:
            save_refiner_base_instructions(raw)
        except ValueError as e:
            messagebox.showwarning("Question refiner", str(e), parent=self._root)
            return
        messagebox.showinfo(
            "Question refiner",
            "Core instructions saved to data/chat/refiner_system_base.txt.",
            parent=self._root,
        )

    def _reset_refiner_system_core(self) -> None:
        if not hasattr(self, "_refiner_sys_core"):
            return
        clear_refiner_base_instructions_override()
        try:
            body = load_refiner_base_instructions()
        except RefineError as e:
            messagebox.showerror("Question refiner", str(e), parent=self._root)
            return
        self._refiner_sys_core.delete("1.0", END)
        self._refiner_sys_core.insert("1.0", body)

    def _reload_refiner_system_core(self) -> None:
        if not hasattr(self, "_refiner_sys_core"):
            return
        try:
            body = load_refiner_base_instructions()
        except RefineError as e:
            messagebox.showerror("Question refiner", str(e), parent=self._root)
            return
        self._refiner_sys_core.delete("1.0", END)
        self._refiner_sys_core.insert("1.0", body)

    def _save_step5_system_core(self) -> None:
        if not hasattr(self, "_step5_sys_core"):
            return
        raw = self._step5_sys_core.get("1.0", END).strip()
        try:
            save_step5_base_instructions(raw)
        except ValueError as e:
            messagebox.showwarning("Step 5", str(e), parent=self._root)
            return
        messagebox.showinfo(
            "Step 5",
            "Core instructions saved to data/chat/step5_system_base.txt.",
            parent=self._root,
        )

    def _reset_step5_system_core(self) -> None:
        if not hasattr(self, "_step5_sys_core"):
            return
        clear_step5_base_instructions_override()
        try:
            body = load_step5_base_instructions()
        except (OSError, FileNotFoundError) as e:
            messagebox.showerror("Step 5", str(e), parent=self._root)
            return
        self._step5_sys_core.delete("1.0", END)
        self._step5_sys_core.insert("1.0", body)

    def _reload_step5_system_core(self) -> None:
        if not hasattr(self, "_step5_sys_core"):
            return
        try:
            body = load_step5_base_instructions()
        except (OSError, FileNotFoundError) as e:
            messagebox.showerror("Step 5", str(e), parent=self._root)
            return
        self._step5_sys_core.delete("1.0", END)
        self._step5_sys_core.insert("1.0", body)

    def _build_bot2_tab(self, tab: ttk.Frame) -> None:
        lf = self._latin
        self._pack_step_main_heading(tab, "Step 2 — Bot 2")
        b2 = load_bot2_ui_settings()
        self._bot2_max_syn_var = tk.StringVar(value=str(b2.max_synonyms))
        intro = ttk.Label(
            tab,
            wraplength=760,
            justify="left",
            font=(lf, 10),
            text=(
                "For each **connotation** from the latest Bot 1 run in this session, "
                "calls the OpenAI **Responses API** with tool **save_arabic_synonyms** to propose "
                "**Arabic synonyms**. Each successful connotation is saved to the database "
                "immediately (so partial progress survives a crash). Results go to "
                "bot2_synonym_runs / bot2_synonym_terms (one pipeline row per connotation). "
                "Configure model, optional file_search stores, max synonyms, and temperature below "
                "(see OpenAI admin for vector stores)."
            ),
        )
        intro.pack(anchor="w", pady=(0, 6), padx=6)

        sys2_lf = ttk.Labelframe(
            tab,
            text="System instructions (Responses API `instructions`)",
            padding=(8, 6),
        )
        sys2_lf.pack(fill="both", expand=False, padx=6, pady=(0, 8))
        ttk.Label(
            sys2_lf,
            wraplength=740,
            justify="left",
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
            text=(
                "The model receives the editable core below plus a block that sets the synonym cap "
                "(from «Max synonyms per connotation») and the save_arabic_synonyms tool text. "
                "«Save core to disk» writes data/chat/bot2_system_base.txt; "
                "«Run Bot 2» uses the current editor text."
            ),
        ).pack(anchor="w", pady=(0, 6))
        sys2_btn = ttk.Frame(sys2_lf)
        sys2_btn.pack(fill="x", pady=(0, 4))
        ttk.Button(
            sys2_btn,
            text="Save core to disk",
            command=self._save_bot2_system_core,
            width=18,
        ).pack(side=tk.LEFT)
        ttk.Button(
            sys2_btn,
            text="Reset core to built-in doc",
            command=self._reset_bot2_system_core,
            width=22,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            sys2_btn,
            text="Reload core from disk / doc",
            command=self._reload_bot2_system_core,
            width=24,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(sys2_lf, text="Core (editable):", font=(lf, 9)).pack(anchor="w")
        core2_fr = ttk.Frame(sys2_lf)
        core2_fr.pack(fill="both", expand=True, pady=(2, 6))
        self._bot2_sys_core = tk.Text(
            core2_fr,
            height=9,
            wrap="word",
            relief="flat",
            font=("Consolas", 9),
        )
        sb2c = ttk.Scrollbar(
            core2_fr, orient=VERTICAL, command=self._bot2_sys_core.yview
        )
        self._bot2_sys_core.configure(yscrollcommand=sb2c.set)
        self._bot2_sys_core.pack(side=LEFT, fill=BOTH, expand=True)
        sb2c.pack(side=RIGHT, fill="y")
        try:
            _b2_core = load_bot2_base_instructions()
        except Bot2Error as e:
            _b2_core = f"(Could not load built-in instructions: {e})"
        self._bot2_sys_core.insert("1.0", _b2_core)
        ttk.Label(
            sys2_lf,
            text="Appended on every run from max-synonyms setting + tool (read-only; updates when you change max synonyms):",
            font=(lf, 9),
        ).pack(anchor="w")
        pers2_fr = ttk.Frame(sys2_lf)
        pers2_fr.pack(fill="x", pady=(2, 0))
        self._bot2_sys_suffix = tk.Text(
            pers2_fr,
            height=5,
            wrap="word",
            state="disabled",
            relief="flat",
            font=("Consolas", 9),
        )
        style_tk_text_readonly(
            self._bot2_sys_suffix, family="Consolas", size=9, monospace=True
        )
        self._bot2_sys_suffix.configure(state="normal")
        try:
            _ms = int(self._bot2_max_syn_var.get().strip() or "8")
        except ValueError:
            _ms = 8
        self._bot2_sys_suffix.insert(
            "1.0", bot2_instructions_suffix(_ms).lstrip("\n")
        )
        self._bot2_sys_suffix.configure(state="disabled")
        sb2p = ttk.Scrollbar(
            pers2_fr, orient=VERTICAL, command=self._bot2_sys_suffix.yview
        )
        self._bot2_sys_suffix.configure(yscrollcommand=sb2p.set)
        self._bot2_sys_suffix.pack(side=LEFT, fill="x", expand=True)
        sb2p.pack(side=RIGHT, fill="y")
        self._bot2_max_syn_var.trace_add("write", self._sync_bot2_system_suffix_preview)

        model_row = ttk.Frame(tab)
        model_row.pack(fill="x", padx=6, pady=(2, 2))
        ttk.Label(model_row, text="Model id (Responses API):", font=(lf, 9)).pack(side=tk.LEFT)
        self._bot2_model_var = tk.StringVar(value=load_bot2_ui_model())
        self._bot2_model_effective = tk.StringVar(value="")
        self._bot2_model_combo = ttk.Combobox(
            model_row,
            textvariable=self._bot2_model_var,
            width=34,
            values=RESPONSES_TOOL_MODEL_CHOICES,
        )
        self._bot2_model_combo.pack(side=tk.LEFT, padx=(8, 0))
        self._bot2_model_combo.bind("<FocusOut>", self._on_bot2_model_focus_out)
        self._bot2_model_var.trace_add("write", self._on_bot2_model_var_write)

        ttk.Label(
            tab,
            textvariable=self._bot2_model_effective,
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
        ).pack(anchor="w", padx=6)
        ttk.Label(
            tab,
            text=(
                "Leave blank to use OPENAI_MODEL_BOT2, then OPENAI_MODEL from .env "
                f"(fallback {resolve_bot2_model('')!r})."
            ),
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=6, pady=(0, 4))

        opt_row = ttk.Frame(tab)
        opt_row.pack(fill="x", padx=6, pady=(2, 4))
        ttk.Label(opt_row, text="Max synonyms per connotation:", font=(lf, 9)).pack(
            side=tk.LEFT
        )
        self._bot2_max_spin = ttk.Spinbox(
            opt_row, from_=1, to=30, width=6, textvariable=self._bot2_max_syn_var
        )
        self._bot2_max_spin.pack(side=tk.LEFT, padx=(8, 16))
        self._bot2_max_spin.bind("<FocusOut>", self._on_bot2_numeric_focus_out)
        ttk.Label(opt_row, text="Temperature (optional):", font=(lf, 9)).pack(side=tk.LEFT)
        self._bot2_temp_var = tk.StringVar(
            value="" if b2.temperature is None else str(b2.temperature)
        )
        t2 = ttk.Entry(opt_row, textvariable=self._bot2_temp_var, width=8)
        t2.pack(side=tk.LEFT, padx=(8, 0))
        t2.bind("<FocusOut>", self._on_bot2_numeric_focus_out)

        self._bot2_skip_existing_var = tk.BooleanVar(value=bool(b2.skip_existing_bot2))
        skip_fr = ttk.Frame(tab)
        skip_fr.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Checkbutton(
            skip_fr,
            text=(
                "Skip connotations that already have Bot 2 synonyms "
                "(for the current Bot 1 run)"
            ),
            variable=self._bot2_skip_existing_var,
            command=self._save_bot2_skip_existing_pref,
        ).pack(anchor="w")

        self._bot2_status = tk.StringVar(value="")
        self._sync_bot2_effective_model()
        ttk.Label(tab, textvariable=self._bot2_status, font=(lf, 9)).pack(
            anchor="w", pady=(6, 4), padx=6
        )

        b2_fr = ttk.Frame(tab)
        b2_fr.pack(fill="x", pady=(4, 8), padx=6)
        rk2: dict = {
            "text": "Run Bot 2 (all connotations)",
            "command": self._run_bot2_pipeline,
            "width": 28,
        }
        if self._icons.get("smart_toy"):
            rk2["image"] = self._icons.get("smart_toy")
            rk2["compound"] = "left"
        self._bot2_run_btn = ttk.Button(b2_fr, **rk2)
        self._bot2_run_btn.pack(side=tk.LEFT)
        self._bot2_stop_btn = ttk.Button(
            b2_fr,
            text="Stop Bot 2",
            command=self._request_stop_bot2,
            width=14,
            state="disabled",
        )
        self._bot2_stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._bot2_copy_err_btn = ttk.Button(
            b2_fr,
            text="Copy last Bot 2 error",
            command=self._copy_bot2_error_to_clipboard,
            width=22,
            state="disabled",
        )
        self._bot2_copy_err_btn.pack(side=tk.LEFT, padx=(12, 0))

        out2 = ttk.Frame(tab)
        out2.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))
        self._bot2_preview = tk.Text(
            out2,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        style_tk_text_readonly(self._bot2_preview, family=lf, size=10, monospace=True)
        self._bot2_preview.configure(font=("Consolas", 10))
        sb2 = ttk.Scrollbar(out2, orient=VERTICAL, command=self._bot2_preview.yview)
        self._bot2_preview.configure(yscrollcommand=sb2.set)
        self._bot2_preview.pack(side=LEFT, fill=BOTH, expand=True)
        sb2.pack(side=RIGHT, fill="y")

    def _build_find_verses_tab(self, tab: ttk.Frame) -> None:
        lf = self._latin
        self._pack_step_main_heading(tab, "Step 3 — Find Verses")
        intro = ttk.Label(
            tab,
            wraplength=760,
            justify="left",
            font=(lf, 10),
            text=(
                "Local scan of quran_tokens (no OpenAI). "
                "Uses the latest Bot 1 run for this session. For each connotation, searches "
                "match-normalized Arabic (including ة/ه): multi-word phrases must match as an exact "
                "contiguous token sequence; a single-word query (3+ letters) also matches a longer "
                "corpus token that contains it (e.g. نفس matches الانفس in 39:42). Synonyms use the "
                "same rules. Re-running replaces all saved matches for this session.\n\n"
                "Important: you need the full Quran in quran_tokens — not just words.example.json "
                "(four words of al-Fātihah 1:1). Import a complete word-by-word JSON "
                "(see README → Import Quran words)."
            ),
        )
        intro.pack(anchor="w", pady=(0, 6), padx=6)

        ttk.Label(
            tab,
            text="Find Verses scorecard (saved pipeline matches)",
            font=(lf, 10, "bold"),
        ).pack(anchor="w", padx=6, pady=(10, 2))
        ttk.Label(
            tab,
            text=(
                "Counts come from the database after «Run Find Verses & save». "
                "The chart is per Bot 1 connotation (order preserved): blue = hits from the "
                "connotation phrase, green = hits from Bot 2 synonyms."
            ),
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=6, pady=(0, 4))
        sc_row = ttk.Frame(tab)
        sc_row.pack(fill="x", padx=6, pady=(0, 6))
        self._fv_score_var_bot1 = tk.StringVar(value="—")
        self._fv_score_var_connotations = tk.StringVar(value="—")
        self._fv_score_var_hit_rows = tk.StringVar(value="—")
        self._fv_score_var_ayahs = tk.StringVar(value="—")
        self._fv_score_var_coverage = tk.StringVar(value="—")
        _tiles: tuple[tuple[str, tk.StringVar], ...] = (
            ("Bot 1 run loaded", self._fv_score_var_bot1),
            ("Connotations", self._fv_score_var_connotations),
            ("Verse hit rows", self._fv_score_var_hit_rows),
            ("Unique ayahs", self._fv_score_var_ayahs),
            ("Connotations w/ hit", self._fv_score_var_coverage),
        )
        for t_title, t_var in _tiles:
            box = ttk.Labelframe(sc_row, text=t_title, padding=(8, 6))
            box.pack(side=LEFT, padx=(0, 6), fill="x", expand=True)
            ttk.Label(box, textvariable=t_var, font=(lf, 13, "bold")).pack(anchor="center")

        self._fv_chart_holder = ttk.Frame(tab)
        self._fv_chart_holder.pack(fill=BOTH, expand=True, padx=6, pady=(0, 8))
        self._fv_stats_mpl_canvas: Any = None

        ttk.Label(
            tab,
            text="Quick search — Arabic only (preview in panel below; use Save to persist)",
            font=(lf, 9, "bold"),
        ).pack(anchor="w", padx=6, pady=(8, 2))
        adhoc_in = ttk.Frame(tab)
        adhoc_in.pack(fill="x", padx=6, pady=(0, 4))
        self._adhoc_arabic_input = tk.Text(
            adhoc_in,
            height=3,
            width=60,
            wrap="word",
            relief="flat",
            font=(self._arabic, 12),
        )
        self._adhoc_arabic_input.pack(side=LEFT, fill="x", expand=True, padx=(0, 8))
        style_tk_text_input(self._adhoc_arabic_input, family=self._arabic, size=12)
        adhoc_btns = ttk.Frame(adhoc_in)
        adhoc_btns.pack(side=LEFT, anchor="n")
        self._adhoc_search_btn = ttk.Button(
            adhoc_btns,
            text="Search Quran",
            command=self._run_adhoc_verse_search,
            width=16,
        )
        self._adhoc_search_btn.pack(anchor="w", pady=(0, 4))
        self._adhoc_save_btn = ttk.Button(
            adhoc_btns,
            text="Save preview to database",
            command=self._save_adhoc_verse_preview,
            width=22,
            state="disabled",
        )
        self._adhoc_save_btn.pack(anchor="w")

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill="x", padx=6, pady=(10, 8))

        fv_main_card = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
        fv_main_card.pack(fill=BOTH, expand=True, padx=6, pady=(0, 8))
        ttk.Label(
            fv_main_card,
            text="Run Find Verses & preview",
            style="SectionHeading.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            fv_main_card,
            text=(
                "Primary action for this step: scan quran_tokens using this session’s Bot 1 + Bot 2 data "
                "and save matches. The text area shows quick-search preview (until saved) and saved pipeline output."
            ),
            style="Hint.TLabel",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        self._fv_pipeline_main = ttk.Frame(fv_main_card, style="Card.TFrame")
        self._fv_pipeline_main.pack(fill=BOTH, expand=True)

        fv_fr = ttk.Frame(self._fv_pipeline_main, style="Card.TFrame")
        fv_fr.pack(fill="x", pady=(0, 8))
        fv_kw: dict = {
            "text": "Run Find Verses & save",
            "command": self._run_find_verses,
            "style": "Accent.TButton",
        }
        if self._icons.get("smart_toy"):
            fv_kw["image"] = self._icons.get("smart_toy")
            fv_kw["compound"] = "left"
        self._find_verses_run_btn = ttk.Button(fv_fr, **fv_kw)
        self._find_verses_run_btn.pack(side=tk.LEFT)

        self._find_verses_status = tk.StringVar(value="")
        ttk.Label(
            self._fv_pipeline_main,
            textvariable=self._find_verses_status,
            style="Status.TLabel",
        ).pack(anchor="w", pady=(0, 6))

        fv_preview_fr = ttk.Frame(self._fv_pipeline_main, style="Card.TFrame")
        fv_preview_fr.pack(fill=BOTH, expand=True, pady=(0, 0))
        self._find_verses_preview = tk.Text(
            fv_preview_fr,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        style_tk_text_readonly(self._find_verses_preview, family=self._arabic, size=12)
        sb_fv = ttk.Scrollbar(fv_preview_fr, orient=VERTICAL, command=self._find_verses_preview.yview)
        self._find_verses_preview.configure(yscrollcommand=sb_fv.set)
        self._find_verses_preview.pack(side=LEFT, fill=BOTH, expand=True)
        sb_fv.pack(side=RIGHT, fill="y")

        fv_table_section = ttk.Frame(tab)
        ttk.Label(
            fv_table_section,
            text="Table: pipeline Find Verses results (verse hits and no-match queries)",
            font=(lf, 11, "bold"),
        ).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            fv_table_section,
            text=(
                "Found rows come from the database (saved matches). "
                "No-match rows are from the last «Run Find Verses & save» for this session."
            ),
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
        ).pack(anchor="w", pady=(0, 2))
        self._fv_not_found_hint = tk.StringVar(value="")
        ttk.Label(fv_table_section, textvariable=self._fv_not_found_hint, font=(lf, 8), wraplength=720).pack(
            anchor="w", pady=(0, 4)
        )
        fv_search_row = ttk.Frame(fv_table_section)
        fv_search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(fv_search_row, text="Search table:", font=(lf, 9)).pack(side=LEFT)
        self._fv_table_search_var = tk.StringVar(value="")
        self._fv_table_search_var.trace_add(
            "write",
            lambda *_a: self._apply_fv_pipeline_table_filter(),
        )
        self._fv_table_search_entry = ttk.Entry(
            fv_search_row,
            textvariable=self._fv_table_search_var,
            width=48,
        )
        self._fv_table_search_entry.pack(side=LEFT, padx=(8, 8), fill="x", expand=True)
        ttk.Button(
            fv_search_row,
            text="Clear",
            command=self._clear_fv_table_search,
            width=8,
        ).pack(side=LEFT)
        ttk.Label(
            fv_table_section,
            text=(
                "Matches any column by substring, or use surah:ayah (e.g. 6:40) to show only that verse’s "
                "hit row(s)."
            ),
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))
        nf_tr = ttk.Frame(fv_table_section)
        nf_tr.pack(fill=BOTH, expand=True)
        nf_tr.rowconfigure(0, weight=1)
        nf_tr.columnconfigure(0, weight=1)
        nf_style = ttk.Style()
        nf_style.configure("FVPipeline.Treeview", rowheight=36, font=(self._arabic, 13))
        nf_style.configure("FVPipeline.Treeview.Heading", font=(lf, 10, "bold"))
        nfc = (
            "row_no",
            "result",
            "match_type",
            "connotation_id",
            "synonym_term_id",
            "verse_ref",
            "query_text",
            "verse_arabic",
        )
        self._fv_pipeline_tree = ttk.Treeview(
            nf_tr,
            columns=nfc,
            show="headings",
            style="FVPipeline.Treeview",
            height=10,
            selectmode="browse",
        )
        C = MaterialColors
        self._fv_pipeline_tree.tag_configure("fv_hit_even", background=C.tree_hit_a)
        self._fv_pipeline_tree.tag_configure("fv_hit_odd", background=C.tree_hit_b)
        self._fv_pipeline_tree.tag_configure("nf_even", background=C.tree_zebra_a)
        self._fv_pipeline_tree.tag_configure("nf_odd", background=C.tree_zebra_b)
        self._fv_pipeline_tree.heading("row_no", text="#")
        self._fv_pipeline_tree.heading("result", text="Result")
        self._fv_pipeline_tree.heading("match_type", text="Type")
        self._fv_pipeline_tree.heading("connotation_id", text="Connotation #")
        self._fv_pipeline_tree.heading("synonym_term_id", text="Syn. #")
        self._fv_pipeline_tree.heading("verse_ref", text="Verse")
        self._fv_pipeline_tree.heading("query_text", text="Arabic query")
        self._fv_pipeline_tree.heading("verse_arabic", text="Verse Arabic Text")
        self._fv_pipeline_tree.column("row_no", width=44, stretch=False, anchor="e")
        self._fv_pipeline_tree.column("result", width=76, stretch=False, anchor="w")
        self._fv_pipeline_tree.column("match_type", width=96, stretch=False, anchor="w")
        self._fv_pipeline_tree.column("connotation_id", width=88, stretch=False, anchor="center")
        self._fv_pipeline_tree.column("synonym_term_id", width=64, stretch=False, anchor="center")
        self._fv_pipeline_tree.column("verse_ref", width=72, stretch=False, anchor="center")
        self._fv_pipeline_tree.column("query_text", width=220, stretch=True, anchor="w")
        self._fv_pipeline_tree.column("verse_arabic", width=260, stretch=True, anchor="w")
        sb_nf = ttk.Scrollbar(nf_tr, orient=VERTICAL, command=self._fv_pipeline_tree.yview)
        sb_nf_h = ttk.Scrollbar(nf_tr, orient=HORIZONTAL, command=self._fv_pipeline_tree.xview)
        self._fv_pipeline_tree.configure(
            yscrollcommand=sb_nf.set,
            xscrollcommand=sb_nf_h.set,
        )
        self._fv_pipeline_tree.grid(row=0, column=0, sticky="nsew")
        sb_nf.grid(row=0, column=1, sticky="ns")
        sb_nf_h.grid(row=1, column=0, sticky="ew")
        self._fv_pipeline_tree.bind("<Button-1>", self._on_fv_pipeline_tree_cell_click, add=True)

        fv_table_section.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))

    def _build_step4_kalimat_tab(self, tab: ttk.Frame) -> None:
        lf = self._latin
        self._pack_step_main_heading(tab, "Step 4 — Kalimat (morphology)")
        intro = ttk.Label(
            tab,
            wraplength=760,
            justify="left",
            font=(lf, 10),
            text=(
                "Table: each row is one verse hit from Step 3 (saved find_verse_matches). "
                "It shows the Bot 1 topic, connotation, whether the hit came from the connotation "
                "phrase or a Bot 2 synonym, the Arabic query that matched, the verse reference, "
                "and how every word in that ayah breaks into kalimat (from quran_token_kalimah). "
                "Load morphology via python database.py (see README). Click a cell to copy. "
                "Select a row to see each morpheme's corpus root (ROOT:) in Root Words below. "
                "Verse roots tab still shows the lexicon breakdown for any loaded ayah."
            ),
        )
        intro.pack(anchor="w", pady=(0, 8), padx=6)

        btn_row = ttk.Frame(tab)
        btn_row.pack(anchor="w", padx=6, pady=(0, 6))
        ttk.Button(
            btn_row,
            text="Refresh table & stats",
            command=lambda: self._refresh_step4_tab(record_summary=True),
            width=22,
        ).pack(side=tk.LEFT)

        table_lf = ttk.Labelframe(tab, text="Pipeline hits — topic, query, verse, kalimat", padding=(4, 6))
        table_lf.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))

        s4_style = ttk.Style(self._root)
        s4_style.configure("Step4.Treeview", rowheight=40, font=(self._arabic, 12))
        s4_style.configure("Step4.Treeview.Heading", font=(lf, 9, "bold"))

        cols = (
            "row_no",
            "topic",
            "connotation",
            "via",
            "synonym",
            "query",
            "verse",
            "kalimat",
        )
        tr = ttk.Frame(table_lf)
        tr.pack(fill=BOTH, expand=True)
        self._step4_pipeline_tree = ttk.Treeview(
            tr,
            columns=cols,
            show="headings",
            style="Step4.Treeview",
            height=10,
            selectmode="browse",
        )
        self._step4_pipeline_tree.tag_configure("s4_even", background=MaterialColors.tree_zebra_a)
        self._step4_pipeline_tree.tag_configure("s4_odd", background=MaterialColors.tree_zebra_b)
        self._step4_pipeline_tree.heading("row_no", text="#")
        self._step4_pipeline_tree.heading("topic", text="Topic")
        self._step4_pipeline_tree.heading("connotation", text="Connotation")
        self._step4_pipeline_tree.heading("via", text="Match via")
        self._step4_pipeline_tree.heading("synonym", text="Synonym (if any)")
        self._step4_pipeline_tree.heading("query", text="Query matched")
        self._step4_pipeline_tree.heading("verse", text="Verse")
        self._step4_pipeline_tree.heading("kalimat", text="Kalimat (per word: n:seg · seg | …)")
        self._step4_pipeline_tree.column("row_no", width=36, stretch=False, anchor="e")
        self._step4_pipeline_tree.column("topic", width=140, stretch=True, anchor="w")
        self._step4_pipeline_tree.column("connotation", width=160, stretch=True, anchor="w")
        self._step4_pipeline_tree.column("via", width=96, stretch=False, anchor="w")
        self._step4_pipeline_tree.column("synonym", width=120, stretch=True, anchor="w")
        self._step4_pipeline_tree.column("query", width=160, stretch=True, anchor="w")
        self._step4_pipeline_tree.column("verse", width=56, stretch=False, anchor="center")
        self._step4_pipeline_tree.column("kalimat", width=420, stretch=True, anchor="w")
        vsb = ttk.Scrollbar(tr, orient=VERTICAL, command=self._step4_pipeline_tree.yview)
        hsb = ttk.Scrollbar(tr, orient=HORIZONTAL, command=self._step4_pipeline_tree.xview)
        self._step4_pipeline_tree.configure(
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )
        self._step4_pipeline_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tr.rowconfigure(0, weight=1)
        tr.columnconfigure(0, weight=1)
        self._step4_pipeline_tree.bind(
            "<Button-1>", self._on_step4_pipeline_tree_cell_click, add=True
        )
        self._step4_pipeline_tree.bind(
            "<<TreeviewSelect>>", self._on_step4_pipeline_tree_select, add=True
        )

        stats_lf = ttk.Labelframe(tab, text="Morphology corpus status", padding=(4, 6))
        stats_lf.pack(fill="x", padx=6, pady=(0, 8))
        self._step4_stats_text = tk.Text(
            stats_lf,
            wrap="word",
            state="disabled",
            relief="flat",
            height=7,
        )
        style_tk_text_readonly(self._step4_stats_text, family=lf, size=9, monospace=True)
        ssb = ttk.Scrollbar(stats_lf, orient=VERTICAL, command=self._step4_stats_text.yview)
        self._step4_stats_text.configure(yscrollcommand=ssb.set)
        self._step4_stats_text.pack(side=LEFT, fill="x", expand=True)
        ssb.pack(side=RIGHT, fill="y")

        roots_lf = ttk.Labelframe(tab, text="Root Words", padding=(4, 6))
        roots_lf.pack(fill=BOTH, expand=True, padx=6, pady=(0, 8))
        roots_wrap = ttk.Frame(roots_lf)
        roots_wrap.pack(fill=BOTH, expand=True)
        self._step4_roots_text = tk.Text(
            roots_wrap,
            wrap="word",
            state="disabled",
            relief="flat",
            height=14,
            cursor="arrow",
        )
        style_tk_text_readonly(self._step4_roots_text, family=lf, size=10)
        self._step4_roots_text.tag_configure(
            "ayah_title", font=(lf, 11, "bold"), spacing1=4, spacing3=6
        )
        self._step4_roots_text.tag_configure("word_hdr", font=(lf, 10, "bold"))
        self._step4_roots_text.tag_configure("arabic", font=(self._arabic, 13))
        self._step4_roots_text.tag_configure(
            "root_ar", font=(self._arabic, 15), foreground="#1565c0"
        )
        self._step4_roots_text.tag_configure("root_bw", font=(lf, 9), foreground="#5f6368")
        self._step4_roots_text.tag_configure("pos", font=(lf, 9), foreground="#757575")
        self._step4_roots_text.tag_configure("hint", font=(lf, 10), foreground="#616161")
        self._step4_roots_text.tag_configure("dim", foreground="#9e9e9e")
        self._step4_roots_text.tag_configure(
            "lane_hdr", font=(lf, 9, "bold"), foreground="#37474f"
        )
        self._step4_roots_text.tag_configure("lane_body", font=(lf, 9), foreground="#455a64")
        self._step4_roots_text.tag_configure(
            "lane_missing", font=(lf, 9, "italic"), foreground="#9e9e9e"
        )
        self._step4_roots_text.tag_configure(
            "lane_link", font=(lf, 9, "underline"), foreground="#1565c0"
        )
        rsb = ttk.Scrollbar(
            roots_wrap, orient=VERTICAL, command=self._step4_roots_text.yview
        )
        self._step4_roots_text.configure(yscrollcommand=rsb.set)
        self._step4_roots_text.pack(side=LEFT, fill=BOTH, expand=True)
        rsb.pack(side=RIGHT, fill="y")

        self._root.after_idle(self._refresh_step4_tab)

    def _refresh_step4_kalimat_stats(self) -> None:
        if not hasattr(self, "_step4_stats_text"):
            return
        db_path = get_db_path()
        lines: list[str] = []
        lines.append("=== Step 4 — Morphological kalimat (local DB) ===\n\n")
        if not db_path.is_file():
            lines.append(f"Database not found:\n  {db_path}\n\nRun: python database.py\n")
        else:
            try:
                conn = connect(db_path)
                try:
                    row = conn.execute(
                        "SELECT COUNT(*) AS n FROM quran_token_kalimah"
                    ).fetchone()
                    n_seg = int(row["n"]) if row else 0
                    row2 = conn.execute(
                        "SELECT COUNT(DISTINCT token_id) AS t FROM quran_token_kalimah"
                    ).fetchone()
                    n_tok = int(row2["t"]) if row2 else 0
                    row3 = conn.execute("SELECT COUNT(*) AS c FROM quran_tokens").fetchone()
                    n_qt = int(row3["c"]) if row3 else 0
                    lines.append(f"Kalimat segment rows:     {n_seg}\n")
                    lines.append(f"Words with morphology:   {n_tok}\n")
                    lines.append(f"Quran word rows (total): {n_qt}\n")
                    if n_qt > 0 and n_tok >= 0:
                        pct = 100.0 * n_tok / n_qt if n_qt else 0.0
                        lines.append(
                            f"Coverage (words with >=1 segment): {pct:.1f}%\n"
                        )
                    lines.append("\n--- Morphology input files ---\n")
                    p_full = RAW_QURAN_DIR / "quran-morphology.txt"
                    p_ex = RAW_QURAN_DIR / "morphology.example.txt"
                    lines.append(
                        f"  {'[ok] ' if p_full.is_file() else '[--] '}{p_full}\n"
                    )
                    lines.append(
                        f"  {'[ok] ' if p_ex.is_file() else '[--] '}{p_ex}\n"
                    )
                    lines.append(
                        "\nImport: python database.py "
                        "(use --skip-kalimah to skip; --morphology-file PATH for a custom file)\n"
                    )
                    if n_seg == 0:
                        lines.append(
                            "\nNo kalimat rows yet. Add a morphology .txt and re-run database.py.\n"
                        )
                finally:
                    conn.close()
            except (OSError, sqlite3.Error) as e:
                lines.append(f"Database error: {e}\n")
        self._step4_stats_text.configure(state="normal")
        self._step4_stats_text.delete("1.0", END)
        self._step4_stats_text.insert("1.0", "".join(lines))
        self._step4_stats_text.configure(state="disabled")

    def _refresh_step4_tab(self, *, record_summary: bool = False) -> None:
        """Reload morphology stats and the pipeline × kalimat table for the current session."""
        sid0 = self._current_id
        if record_summary and sid0:
            self._pipeline_step_start(sid0, 4)
        self._refresh_step4_kalimat_stats()
        if not hasattr(self, "_step4_pipeline_tree"):
            if record_summary and sid0:
                self._pipeline_step_clock.pop((sid0, 4), None)
            return
        tv = self._step4_pipeline_tree
        for item in tv.get_children():
            tv.delete(item)
        sid = self._current_id
        if not sid:
            tv.insert(
                "",
                END,
                values=(
                    "—",
                    "(select a session)",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ),
            )
            self._update_step4_root_words_from_selection()
            if record_summary and sid0:
                self._pipeline_step_clock.pop((sid0, 4), None)
            return
        try:
            conn = connect(get_db_path())
            try:
                rows = fetch_step4_kalimat_pipeline_rows(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            tv.insert(
                "",
                END,
                values=("!", "Database error", str(e), "", "", "", "", ""),
            )
            self._update_step4_root_words_from_selection()
            if record_summary and sid0:
                self._pipeline_step_clock.pop((sid0, 4), None)
            return
        if not rows:
            tv.insert(
                "",
                END,
                values=(
                    "—",
                    "(no saved Find Verses rows)",
                    "Run Step 3, then «Run Find Verses & save».",
                    "",
                    "",
                    "",
                    "",
                    "",
                ),
            )
            self._update_step4_root_words_from_selection()
        else:
            for i, row in enumerate(rows, start=1):
                tag = "s4_even" if i % 2 == 0 else "s4_odd"
                via = (
                    "Connotation phrase"
                    if row.source_kind == "connotation"
                    else "Bot 2 synonym"
                )
                syn = row.synonym_text or ""
                ref = f"{row.surah_no}:{row.ayah_no}"
                tv.insert(
                    "",
                    END,
                    values=(
                        str(i),
                        row.topic_text,
                        row.connotation_text,
                        via,
                        syn,
                        row.query_text,
                        ref,
                        row.kalimat_breakdown,
                    ),
                    tags=(tag, f"fmid_{row.find_match_id}"),
                )
        if record_summary and sid:
            nrows = len(rows)
            self._pipeline_step_finish_from_partial(
                sid,
                4,
                agent=False,
                in_tok=0,
                out_tok=0,
                in_usd=0.0,
                out_usd=0.0,
                models=f"DB kalimat view ({nrows} pipeline row(s))",
            )
        self._update_step4_root_words_from_selection()

    def _on_step4_pipeline_tree_cell_click(self, event: tk.Event) -> None:
        if not hasattr(self, "_step4_pipeline_tree"):
            return
        tv = self._step4_pipeline_tree
        if tv.identify_region(event.x, event.y) != "cell":
            return
        row_id = tv.identify_row(event.y)
        col_id = tv.identify_column(event.x)
        if not row_id:
            return
        try:
            n = int(str(col_id).lstrip("#"))
        except ValueError:
            return
        if n < 1:
            return
        idx = n - 1
        vals = tv.item(row_id, "values")
        if idx >= len(vals):
            return
        text = str(vals[idx] if vals[idx] is not None else "")
        try:
            self._root.clipboard_clear()
            self._root.clipboard_append(text)
            self._root.update_idletasks()
        except tk.TclError:
            pass

    def _on_step4_pipeline_tree_select(self, _event: tk.Event | None = None) -> None:
        self._update_step4_root_words_from_selection()

    _STEP4_LANE_INLINE_MAX = 2800

    def _on_step4_lane_link_click(self, title: str, body: str) -> None:
        fn = self._on_lexicon_definition
        if fn:
            fn(title, body)
        else:
            messagebox.showinfo(title, body[:8000] + ("…" if len(body) > 8000 else ""))

    def _append_step4_lane_block_for_morpheme(
        self, tw: tk.Text, conn: sqlite3.Connection, m: MorphemeRootRow
    ) -> None:
        """Insert Lane lexicon headings + definitions under one morphology row (same DB link as Verse roots)."""
        if not m.root_arabic and not m.root_buckwalter:
            return
        entries = fetch_lane_lexicon_for_morph_root(
            conn,
            root_arabic=m.root_arabic,
            root_buckwalter=m.root_buckwalter,
        )
        if not entries:
            tw.insert(END, "     Lane: ", ("dim",))
            tw.insert(
                END,
                "(no matching Lane lexicon root — import lane_lexicon*.json)\n",
                ("lane_missing",),
            )
            return

        def _definition_word_count(s: str) -> int:
            return len((s or "").split())

        total_words = sum(_definition_word_count((h.definition or "").strip()) for h in entries)
        n_ent = len(entries)
        ent_lbl = "entry" if n_ent == 1 else "entries"
        tw.insert(END, "     Lane (lexicon) — ", ("dim",))
        tw.insert(END, f"{total_words} words", ("lane_hdr",))
        tw.insert(END, f" in {n_ent} {ent_lbl}:\n", ("dim",))
        cap = self._STEP4_LANE_INLINE_MAX
        for h in entries:
            disp_head = heading_display_label(h.label)
            title = entry_dialog_title(h.seq, h.label)
            raw_def = (h.definition or "").strip()
            wc = _definition_word_count(raw_def)
            shaped_full = shape_arabic_display(raw_def) if raw_def else ""
            tw.insert(END, "       • ", ("dim",))
            tw.insert(END, (disp_head if disp_head.strip() else f"Entry {h.seq}"), ("lane_hdr",))
            tw.insert(END, f" — {wc} words\n", ("dim",))
            if not shaped_full:
                tw.insert(END, "         (empty definition)\n", ("lane_missing",))
                continue
            if len(shaped_full) <= cap:
                tw.insert(END, "         ", ("dim",))
                tw.insert(END, shaped_full + "\n", ("lane_body",))
            else:
                shown = shaped_full[:cap].rstrip() + "…\n"
                tw.insert(END, "         ", ("dim",))
                tw.insert(END, shown, ("lane_body",))
                self._step4_lane_tag_seq += 1
                tname = f"s4lane_{self._step4_lane_tag_seq}"
                tw.insert(END, "         ", ("dim",))
                tw.insert(END, "Open full entry…\n", (tname, "lane_link"))

                def _open(_e: tk.Event, ti: str = title, bd: str = raw_def) -> None:
                    self._on_step4_lane_link_click(ti, bd)

                tw.tag_bind(tname, "<Button-1>", _open)
                tw.tag_bind(
                    tname,
                    "<Enter>",
                    lambda _e: tw.configure(cursor="hand2"),
                )
                tw.tag_bind(
                    tname,
                    "<Leave>",
                    lambda _e: tw.configure(cursor="arrow"),
                )

    def _update_step4_root_words_from_selection(self) -> None:
        if not hasattr(self, "_step4_roots_text"):
            return
        tw = self._step4_roots_text
        tv = self._step4_pipeline_tree
        tw.configure(state="normal")
        tw.delete("1.0", END)
        self._step4_lane_tag_seq = 0
        sel = tv.selection()
        if not sel:
            tw.insert(
                END,
                "Select a row in the table above to see each morpheme's corpus root "
                "(from morphology ROOT: tags).",
                ("hint",),
            )
            tw.configure(state="disabled")
            return
        vals = tv.item(sel[0], "values")
        if not vals or len(vals) < 7:
            tw.insert(END, "Could not read the selected row.", ("hint",))
            tw.configure(state="disabled")
            return
        ref = str(vals[6]).strip() if vals[6] is not None else ""
        if ":" not in ref:
            tw.insert(
                END,
                "Choose a pipeline hit row that includes a verse reference (e.g. 2:255).",
                ("hint",),
            )
            tw.configure(state="disabled")
            return
        try:
            su_s, ay_s = ref.split(":", 1)
            su, ay = int(su_s.strip()), int(ay_s.strip())
        except ValueError:
            tw.insert(END, f"Unrecognized verse reference: {ref!r}.", ("hint",))
            tw.configure(state="disabled")
            return
        find_match_id: int | None = None
        for t in tv.item(sel[0], "tags"):
            if isinstance(t, str) and t.startswith("fmid_"):
                try:
                    find_match_id = int(t[5:])
                except ValueError:
                    find_match_id = None
                break
        db_path = get_db_path()
        if not db_path.is_file():
            tw.insert(END, f"Database not found:\n{db_path}", ("hint",))
            tw.configure(state="disabled")
            return
        link_note: str | None = None
        words: list[WordMorphemeRoots] = []
        conn = None
        try:
            conn = connect(db_path)
            if find_match_id is not None:
                tids = fetch_token_ids_for_find_match(conn, find_match_id)
                if tids:
                    words = fetch_morpheme_roots_for_token_ids(conn, tids)
                    link_note = (
                        f"DB link: find_match_word_rows for match id {find_match_id} "
                        f"({len(tids)} word token(s))."
                    )
                else:
                    words = fetch_ayah_morpheme_roots(conn, su, ay)
                    link_note = (
                        f"No find_match_word_rows for match id {find_match_id} "
                        "(verse may be missing from quran_tokens, or re-run Find Verses). "
                        "Showing full ayah from corpus."
                    )
            else:
                words = fetch_ayah_morpheme_roots(conn, su, ay)
        except (OSError, sqlite3.Error) as e:
            if conn is not None:
                conn.close()
            tw.insert(END, f"Database error: {e}", ("hint",))
            tw.configure(state="disabled")
            return
        try:
            tw.insert(END, f"Verse {su}:{ay}", ("ayah_title",))
            tw.insert(END, "\n\n")
            if link_note:
                tw.insert(END, link_note + "\n\n", ("dim",))
            tw.insert(
                END,
                "Each line is one morphological segment; the root is from the corpus ROOT: field "
                "when present. Lane lexicon text (from imported lane_lexicon*.json) is joined on "
                "the same normalized root as the Verse roots tab.\n\n",
                ("dim",),
            )
            if not words:
                tw.insert(
                    END,
                    "No word tokens for this verse in the database (import word-by-word Quran data).",
                    ("hint",),
                )
            else:
                for w in words:
                    tw.insert(END, f"Word {w.word_no}", ("word_hdr",))
                    tw.insert(END, "\n")
                    tw.insert(END, w.token_uthmani, ("arabic",))
                    tw.insert(END, "\n")
                    if not w.morphemes:
                        tw.insert(
                            END, "  (no morphology segments — run morphology import)\n\n", ("dim",)
                        )
                        continue
                    for m in w.morphemes:
                        tw.insert(END, f"  {m.kalimah_seq}. ", ("dim",))
                        tw.insert(END, m.surface, ("arabic",))
                        tw.insert(END, "  ", ("dim",))
                        if m.pos:
                            tw.insert(END, f"{m.pos}  ", ("pos",))
                        tw.insert(END, "→  ", ("dim",))
                        if m.root_arabic:
                            tw.insert(END, m.root_arabic, ("root_ar",))
                        elif m.root_buckwalter:
                            tw.insert(END, m.root_buckwalter, ("root_bw",))
                        else:
                            tw.insert(END, "(no ROOT in tags)", ("dim",))
                        if m.root_buckwalter and m.root_arabic:
                            tw.insert(END, "  ", ("dim",))
                            tw.insert(END, f"({m.root_buckwalter})", ("root_bw",))
                        tw.insert(END, "\n")
                        self._append_step4_lane_block_for_morpheme(tw, conn, m)
                    tw.insert(END, "\n")
        finally:
            if conn is not None:
                conn.close()
        tw.configure(state="disabled")

    def _on_fv_pipeline_tree_cell_click(self, event: tk.Event) -> None:
        """Copy the text of the table cell under the pointer to the system clipboard."""
        if not hasattr(self, "_fv_pipeline_tree"):
            return
        tv = self._fv_pipeline_tree
        if tv.identify_region(event.x, event.y) != "cell":
            return
        row_id = tv.identify_row(event.y)
        col_id = tv.identify_column(event.x)
        if not row_id:
            return
        try:
            n = int(str(col_id).lstrip("#"))
        except ValueError:
            return
        # #0 is the tree column; data columns are #1 .. #n matching `values` order.
        if n < 1:
            return
        idx = n - 1
        vals = tv.item(row_id, "values")
        if idx >= len(vals):
            return
        text = str(vals[idx] if vals[idx] is not None else "")
        try:
            self._root.clipboard_clear()
            self._root.clipboard_append(text)
            self._root.update_idletasks()
        except tk.TclError:
            pass

    def _on_bot2_model_focus_out(self, _event: tk.Event | None = None) -> None:
        save_bot2_ui_model(self._bot2_model_var.get())

    def _on_bot2_model_var_write(self, *_args: object) -> None:
        self._sync_bot2_effective_model()

    def _sync_bot2_effective_model(self) -> None:
        if not hasattr(self, "_bot2_model_effective"):
            return
        self._bot2_model_effective.set(
            "Effective model: " + resolve_bot2_model(self._bot2_model_var.get())
        )

    def _on_bot2_numeric_focus_out(self, _event: tk.Event | None = None) -> None:
        ui = load_bot2_ui_settings()
        ui.model = self._bot2_model_var.get().strip()
        try:
            ui.max_synonyms = max(1, min(30, int(self._bot2_max_syn_var.get())))
        except ValueError:
            ui.max_synonyms = 8
            self._bot2_max_syn_var.set("8")
        raw = self._bot2_temp_var.get().strip()
        ui.temperature = float(raw) if raw else None
        if hasattr(self, "_bot2_skip_existing_var"):
            ui.skip_existing_bot2 = bool(self._bot2_skip_existing_var.get())
        save_bot2_ui_settings(ui)

    def _save_bot2_skip_existing_pref(self) -> None:
        ui = load_bot2_ui_settings()
        if hasattr(self, "_bot2_skip_existing_var"):
            ui.skip_existing_bot2 = bool(self._bot2_skip_existing_var.get())
        save_bot2_ui_settings(ui)

    def _build_step5_tab(self, tab: ttk.Frame) -> None:
        lf = self._latin
        self._pack_step_main_heading(tab, "Step 5 — Theological synthesis")
        intro = ttk.Label(
            tab,
            wraplength=760,
            justify="left",
            font=(lf, 10),
            text=(
                "Step 5 has two substeps: (A) Shortlist — score/filter Step 3 rows. "
                "(B) Synthesis — LLM exegesis jobs (Run Step 5). They use different models unless you "
                "choose the same provider manually. CLEAR removes synthesis only; the shortlist stays."
            ),
        )
        intro.pack(anchor="w", pady=(0, 6), padx=6)

        ui = load_step5_ui_settings()
        self._step5_provider_var = tk.StringVar(value=ui.provider or "openai")
        self._step5_model_var = tk.StringVar(
            value=ui.model or default_model_for_provider(ui.provider)
        )
        self._step5_all_verses_var = tk.BooleanVar(value=bool(ui.all_verses))
        self._step5_verse_n_var = tk.StringVar(value=str(max(1, int(ui.verse_n))))
        self._step5_workers_var = tk.StringVar(value=str(max(1, int(ui.max_workers))))
        rp = int(ui.relevance_threshold_pct) if ui.relevance_threshold_pct else 70
        self._step5_relevance_pct_var = tk.StringVar(
            value=str(max(1, min(100, rp)))
        )
        self._step5_use_shortlist_var = tk.BooleanVar(
            value=bool(getattr(ui, "use_shortlist_for_synthesis", True))
        )
        _sm = str(getattr(ui, "synthesis_mode", "combination") or "combination").strip().lower()
        self._step5_loaded_request_var = tk.BooleanVar(value=_sm == "loaded")
        self._step5_shortlist_status_var = tk.StringVar(value="")
        self._step5_progress_var = tk.StringVar(value="")
        self._step5_request_stats_var = tk.StringVar(value="")
        _sl_m = str(getattr(ui, "shortlist_method", "cross_encoder") or "cross_encoder").strip().lower()
        if _sl_m not in {"cross_encoder", "llm"}:
            _sl_m = "cross_encoder"
        _sl_p = str(getattr(ui, "shortlist_llm_provider", "deepseek") or "deepseek").strip().lower()
        if _sl_p not in {"deepseek", "openai", "openrouter"}:
            _sl_p = "deepseek"
        _sl_mod = str(getattr(ui, "shortlist_llm_model", "") or "").strip()
        if not _sl_mod:
            _sl_mod = default_shortlist_llm_model(_sl_p)
        self._step5_shortlist_method_var = tk.StringVar(value=_sl_m)
        self._step5_shortlist_llm_provider_var = tk.StringVar(value=_sl_p)
        self._step5_shortlist_llm_model_var = tk.StringVar(value=_sl_mod)

        part_a = ttk.Labelframe(
            tab,
            text=(
                "A — Shortlist (substep 1: score & filter Step 3 rows — not the synthesis LLM below)"
            ),
            padding=(8, 6),
        )
        part_a.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Label(
            part_a,
            wraplength=720,
            justify="left",
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
            text=(
                "Pick CrossEncoder (local) or LLM, then set Shortlist provider/model when using LLM. "
                "Click SHORTLIST to write scores; the table shows kept rows."
            ),
        ).pack(anchor="w", pady=(0, 8))

        row2 = ttk.Frame(part_a)
        row2.pack(fill="x", pady=(0, 4))
        self._step5_all_chk = ttk.Checkbutton(
            row2,
            text="All saved verse rows",
            variable=self._step5_all_verses_var,
            command=self._on_step5_all_toggle,
        )
        self._step5_all_chk.pack(side=tk.LEFT)
        ttk.Label(row2, text="or first N rows:", font=(lf, 9)).pack(side=tk.LEFT, padx=(12, 4))
        self._step5_verse_n_entry = ttk.Entry(row2, textvariable=self._step5_verse_n_var, width=8)
        self._step5_verse_n_entry.pack(side=tk.LEFT)
        self._on_step5_all_toggle()

        row2_sl = ttk.Frame(part_a)
        row2_sl.pack(fill="x", pady=(0, 2))
        ttk.Label(row2_sl, text="Scoring technique:", font=(lf, 9)).pack(side=tk.LEFT)
        self._step5_shortlist_rb_ce = ttk.Radiobutton(
            row2_sl,
            text="CrossEncoder (local library)",
            variable=self._step5_shortlist_method_var,
            value="cross_encoder",
            command=self._on_step5_shortlist_method_change,
        )
        self._step5_shortlist_rb_ce.pack(side=tk.LEFT, padx=(8, 0))
        self._step5_shortlist_rb_llm = ttk.Radiobutton(
            row2_sl,
            text="LLM (API)",
            variable=self._step5_shortlist_method_var,
            value="llm",
            command=self._on_step5_shortlist_method_change,
        )
        self._step5_shortlist_rb_llm.pack(side=tk.LEFT, padx=(8, 0))

        row2_sl_llm = ttk.Frame(part_a)
        row2_sl_llm.pack(fill="x", pady=(0, 4))
        self._step5_shortlist_llm_row = row2_sl_llm
        ttk.Label(row2_sl_llm, text="Shortlist LLM provider:", font=(lf, 9)).pack(side=tk.LEFT)
        self._step5_shortlist_llm_provider_combo = ttk.Combobox(
            row2_sl_llm,
            width=11,
            values=("deepseek", "openai", "openrouter"),
            textvariable=self._step5_shortlist_llm_provider_var,
            state="readonly",
        )
        self._step5_shortlist_llm_provider_combo.pack(side=tk.LEFT, padx=(6, 12))
        self._step5_shortlist_llm_provider_combo.bind(
            "<<ComboboxSelected>>", self._on_step5_shortlist_llm_provider_change
        )
        ttk.Label(row2_sl_llm, text="Model:", font=(lf, 9)).pack(side=tk.LEFT)
        self._step5_shortlist_llm_model_combo = ttk.Combobox(
            row2_sl_llm,
            textvariable=self._step5_shortlist_llm_model_var,
            width=28,
            values=(),
        )
        self._step5_shortlist_llm_model_combo.pack(side=tk.LEFT, padx=(6, 0))
        self._sync_step5_shortlist_model_options()
        self._on_step5_shortlist_method_change()

        row2b = ttk.Frame(part_a)
        row2b.pack(fill="x", pady=(0, 4))
        self._step5_shortlist_btn = ttk.Button(
            row2b,
            text="SHORTLIST",
            command=self._run_step5_shortlist,
            width=12,
        )
        self._step5_shortlist_btn.pack(side=tk.LEFT)
        self._step5_shortlist_stop_btn = ttk.Button(
            row2b,
            text="Stop shortlist",
            command=self._request_stop_step5_shortlist,
            width=14,
            state="disabled",
        )
        self._step5_shortlist_stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(row2b, text="Min relevance N%:", font=(lf, 9)).pack(side=tk.LEFT, padx=(10, 4))
        self._step5_relevance_entry = ttk.Entry(
            row2b, textvariable=self._step5_relevance_pct_var, width=6
        )
        self._step5_relevance_entry.pack(side=tk.LEFT, padx=(0, 10))
        self._step5_shortlist_help_var = tk.StringVar()
        self._step5_shortlist_help_label = ttk.Label(
            row2b,
            textvariable=self._step5_shortlist_help_var,
            font=(lf, 8),
            wraplength=520,
            justify="left",
        )
        self._step5_shortlist_help_label.pack(side=tk.LEFT)
        self._update_step5_shortlist_help_text()

        row2b_hint = ttk.Frame(part_a)
        row2b_hint.pack(fill="x", pady=(0, 2))
        ttk.Label(
            row2b_hint,
            text=(
                "While SHORTLIST is running, use «Stop shortlist» to abort. "
                "The saved shortlist is not updated until the run finishes; click SHORTLIST again to rerun (full pass)."
            ),
            font=(lf, 8),
            wraplength=720,
            justify="left",
            foreground=MaterialColors.on_surface_variant,
        ).pack(anchor="w")

        row2c = ttk.Frame(part_a)
        row2c.pack(fill="x", pady=(0, 4))
        self._step5_use_shortlist_chk = ttk.Checkbutton(
            row2c,
            text="Run Step 5 on shortlisted verses only",
            variable=self._step5_use_shortlist_var,
        )
        self._step5_use_shortlist_chk.pack(side=tk.LEFT)

        ttk.Label(
            part_a,
            textvariable=self._step5_shortlist_status_var,
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
        ).pack(anchor="w", pady=(4, 2))

        sl_cols = ("verse", "score", "query")
        sl_fr = ttk.Frame(part_a)
        sl_fr.pack(fill=BOTH, expand=False, pady=(0, 0))
        ttk.Label(sl_fr, text="Shortlist results (after SHORTLIST)", font=(lf, 9, "bold")).pack(
            anchor="w"
        )
        sl_inner = ttk.Frame(sl_fr)
        sl_inner.pack(fill=BOTH, expand=True)
        self._step5_shortlist_tree = ttk.Treeview(
            sl_inner,
            columns=sl_cols,
            show="headings",
            selectmode="browse",
            height=5,
        )
        self._step5_shortlist_tree.heading("verse", text="Verse")
        self._step5_shortlist_tree.heading("score", text="Score")
        self._step5_shortlist_tree.heading("query", text="Find-verses query")
        self._step5_shortlist_tree.column("verse", width=72, stretch=False, anchor="center")
        self._step5_shortlist_tree.column("score", width=72, stretch=False, anchor="e")
        self._step5_shortlist_tree.column("query", width=420, stretch=True, anchor="w")
        sl_sv = ttk.Scrollbar(
            sl_inner, orient=VERTICAL, command=self._step5_shortlist_tree.yview
        )
        self._step5_shortlist_tree.configure(yscrollcommand=sl_sv.set)
        self._step5_shortlist_tree.grid(row=0, column=0, sticky="nsew")
        sl_sv.grid(row=0, column=1, sticky="ns")
        sl_inner.rowconfigure(0, weight=1)
        sl_inner.columnconfigure(0, weight=1)
        self._step5_shortlist_tree.bind(
            "<<TreeviewSelect>>", self._on_step5_shortlist_select, add=True
        )

        part_b = ttk.Labelframe(
            tab,
            text="B — Synthesis run (substep 2: exegesis — Run Step 5 & save to DB)",
            padding=(8, 6),
        )
        part_b.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Label(
            part_b,
            wraplength=720,
            justify="left",
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
            text=(
                "Provider, model, and workers here apply only to synthesis jobs — not to SHORTLIST in A."
            ),
        ).pack(anchor="w", pady=(0, 6))

        row1 = ttk.Frame(part_b)
        row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="Synthesis provider:", font=(lf, 9)).pack(side=tk.LEFT)
        self._step5_provider_combo = ttk.Combobox(
            row1,
            width=12,
            values=("openai", "deepseek", "openrouter"),
            textvariable=self._step5_provider_var,
            state="readonly",
        )
        self._step5_provider_combo.pack(side=tk.LEFT, padx=(6, 12))
        self._step5_provider_combo.bind("<<ComboboxSelected>>", self._on_step5_provider_change)
        ttk.Label(row1, text="Model:", font=(lf, 9)).pack(side=tk.LEFT)
        self._step5_model_combo = ttk.Combobox(
            row1,
            textvariable=self._step5_model_var,
            width=28,
            values=(),
        )
        self._step5_model_combo.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(row1, text="Workers:", font=(lf, 9)).pack(side=tk.LEFT)
        self._step5_workers_entry = ttk.Entry(row1, textvariable=self._step5_workers_var, width=6)
        self._step5_workers_entry.pack(side=tk.LEFT, padx=(6, 12))
        self._step5_loaded_chk = ttk.Checkbutton(
            row1,
            text="Loaded request (all entries per verse)",
            variable=self._step5_loaded_request_var,
        )
        self._step5_loaded_chk.pack(side=tk.LEFT)
        self._sync_step5_model_options()

        btn_row = ttk.Frame(part_b)
        btn_row.pack(anchor="w", pady=(4, 0))
        self._step5_run_btn = ttk.Button(
            btn_row,
            text="Run Step 5 & save to DB",
            command=self._run_step5_pipeline,
            width=24,
        )
        self._step5_run_btn.pack(side=tk.LEFT)
        self._step5_stop_btn = ttk.Button(
            btn_row,
            text="Stop",
            command=self._request_stop_step5,
            width=10,
            state="disabled",
        )
        self._step5_stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._step5_refresh_btn = ttk.Button(
            btn_row,
            text="Refresh",
            command=self._refresh_step5_tab,
            width=12,
        )
        self._step5_refresh_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._step5_clear_btn = ttk.Button(
            btn_row,
            text="CLEAR",
            command=self._clear_step5_synthesis,
            width=10,
        )
        self._step5_clear_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._step5_resume_btn = ttk.Button(
            btn_row,
            text="Resume last run",
            command=self._resume_step5_pipeline,
            width=16,
        )
        self._step5_resume_btn.pack(side=tk.LEFT, padx=(8, 0))

        s5_lf = ttk.Labelframe(
            tab,
            text="C — Synthesis system message (Chat Completions `system` — used only by section B)",
            padding=(8, 6),
        )
        s5_lf.pack(fill="both", expand=False, padx=6, pady=(0, 8))
        ttk.Label(
            s5_lf,
            wraplength=740,
            justify="left",
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
            text=(
                "Full system message for each synthesis call. "
                "«Save core to disk» → data/chat/step5_system_base.txt. "
                "«Run Step 5» uses the editor text (same pattern as Steps 1–2)."
            ),
        ).pack(anchor="w", pady=(0, 6))
        s5_btn = ttk.Frame(s5_lf)
        s5_btn.pack(fill="x", pady=(0, 4))
        ttk.Button(
            s5_btn,
            text="Save core to disk",
            command=self._save_step5_system_core,
            width=18,
        ).pack(side=tk.LEFT)
        ttk.Button(
            s5_btn,
            text="Reset core to built-in doc",
            command=self._reset_step5_system_core,
            width=22,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            s5_btn,
            text="Reload core from disk / doc",
            command=self._reload_step5_system_core,
            width=24,
        ).pack(side=tk.LEFT, padx=(8, 0))
        s5_core_fr = ttk.Frame(s5_lf)
        s5_core_fr.pack(fill="both", expand=True)
        self._step5_sys_core = tk.Text(
            s5_core_fr,
            height=7,
            wrap="word",
            relief="flat",
            font=("Consolas", 9),
        )
        s5_sb = ttk.Scrollbar(
            s5_core_fr, orient=VERTICAL, command=self._step5_sys_core.yview
        )
        self._step5_sys_core.configure(yscrollcommand=s5_sb.set)
        self._step5_sys_core.pack(side=LEFT, fill=BOTH, expand=True)
        s5_sb.pack(side=RIGHT, fill="y")
        try:
            _s5_core = load_step5_base_instructions()
        except (OSError, FileNotFoundError) as e:
            _s5_core = f"(Could not load built-in instructions: {e})"
        self._step5_sys_core.insert("1.0", _s5_core)

        ttk.Label(
            tab,
            textvariable=self._step5_progress_var,
            font=(lf, 9),
            foreground=MaterialColors.on_surface_variant,
        ).pack(anchor="w", padx=6, pady=(0, 2))
        ttk.Label(
            tab,
            textvariable=self._step5_request_stats_var,
            font=(lf, 10, "bold"),
            foreground=MaterialColors.primary,
        ).pack(anchor="w", padx=6, pady=(0, 6))

        stats_lf = ttk.Labelframe(
            tab,
            text=(
                "Run scorecard & charts — requests, input/output tokens, costs, and job status "
                "(full saved results; results table below may list up to 300 rows). "
                "«Save stats snapshot» writes metrics_summary + analytics JSON to the database."
            ),
            padding=(8, 6),
        )
        stats_lf.pack(fill="x", padx=6, pady=(0, 6))
        self._step5_stat_saved_rows = tk.StringVar(value="—")
        self._step5_stat_distinct_verses = tk.StringVar(value="—")
        self._step5_stat_llm_requests = tk.StringVar(value="—")
        self._step5_stat_tokens_in = tk.StringVar(value="—")
        self._step5_stat_tokens_out = tk.StringVar(value="—")
        self._step5_stat_tokens_total = tk.StringVar(value="—")
        self._step5_stat_tokens_avg = tk.StringVar(value="—")
        self._step5_stat_cost = tk.StringVar(value="—")
        self._step5_stat_cost_avg = tk.StringVar(value="—")
        self._step5_stat_scores = tk.StringVar(value="—")
        self._step5_stat_job_mix = tk.StringVar(value="—")
        self._step5_stat_manifest_prog = tk.StringVar(value="—")
        self._step5_stat_failures = tk.StringVar(value="—")

        def _stat_cell(parent: ttk.Frame, r: int, c: int, title: str, var: tk.StringVar) -> None:
            cell = ttk.Frame(parent, padding=(6, 4))
            cell.grid(row=r, column=c, sticky="nw", padx=2, pady=2)
            ttk.Label(
                cell,
                text=title,
                font=(lf, 8),
                foreground=MaterialColors.on_surface_variant,
            ).pack(anchor="w")
            ttk.Label(cell, textvariable=var, font=(lf, 10, "bold"), wraplength=200, justify="left").pack(
                anchor="w"
            )

        stats_grid = ttk.Frame(stats_lf)
        stats_grid.pack(fill="x")
        for col in range(4):
            stats_grid.columnconfigure(col, weight=1)
        _stat_cell(stats_grid, 0, 0, "Saved API results (DB rows)", self._step5_stat_saved_rows)
        _stat_cell(stats_grid, 0, 1, "Distinct verses (ayahs)", self._step5_stat_distinct_verses)
        _stat_cell(
            stats_grid,
            0,
            2,
            "LLM requests (queued job rows)",
            self._step5_stat_llm_requests,
        )
        _stat_cell(
            stats_grid,
            0,
            3,
            "Input tokens (prompt, summed)",
            self._step5_stat_tokens_in,
        )
        _stat_cell(
            stats_grid,
            1,
            0,
            "Output tokens (completion, summed)",
            self._step5_stat_tokens_out,
        )
        _stat_cell(stats_grid, 1, 1, "Total tokens (summed per row)", self._step5_stat_tokens_total)
        _stat_cell(
            stats_grid,
            1,
            2,
            "Avg tokens / saved result (in → out → total)",
            self._step5_stat_tokens_avg,
        )
        _stat_cell(stats_grid, 1, 3, "Total cost (USD)", self._step5_stat_cost)
        _stat_cell(stats_grid, 2, 0, "Avg cost / saved result (USD)", self._step5_stat_cost_avg)
        _stat_cell(stats_grid, 2, 1, "Possibility score", self._step5_stat_scores)
        _stat_cell(stats_grid, 2, 2, "Job status (done / failed / …)", self._step5_stat_job_mix)
        _stat_cell(stats_grid, 2, 3, "Manifest completion", self._step5_stat_manifest_prog)
        _stat_cell(stats_grid, 3, 0, "Failed jobs — error codes (top)", self._step5_stat_failures)

        snap_row = ttk.Frame(stats_lf)
        snap_row.pack(fill="x", pady=(4, 0))
        ttk.Button(
            snap_row,
            text="Save stats snapshot to DB",
            command=self._save_step5_stats_snapshot,
            width=24,
        ).pack(side=tk.LEFT)
        ttk.Label(
            snap_row,
            text="Appends one JSON row to step5_run_stats_snapshots for the current run.",
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
            wraplength=560,
            justify="left",
        ).pack(side=tk.LEFT, padx=(10, 0))

        self._step5_stats_chart_holder = ttk.Frame(stats_lf)
        self._step5_stats_chart_holder.pack(fill="both", expand=False, pady=(6, 0))
        self._step5_stats_mpl_canvas = None

        req_lf = ttk.Labelframe(
            tab,
            text=(
                "LLM API calls (this run) — click a row to expand formatted API response below "
                "(refreshes while Step 5 runs)"
            ),
            padding=(0, 4),
        )
        req_lf.pack(fill=BOTH, expand=False, padx=6, pady=(0, 4))
        req_inner = ttk.Frame(req_lf)
        req_inner.pack(fill=BOTH, expand=True)
        req_cols = ("job", "verse", "status", "progress", "request", "response")
        self._step5_requests_tree = ttk.Treeview(
            req_inner,
            columns=req_cols,
            show="headings",
            selectmode="browse",
            height=8,
        )
        self._step5_requests_tree.heading("job", text="Job #")
        self._step5_requests_tree.heading("verse", text="Verse")
        self._step5_requests_tree.heading("status", text="State")
        self._step5_requests_tree.heading("progress", text="Live progress")
        self._step5_requests_tree.heading("request", text="Request (preview)")
        self._step5_requests_tree.heading("response", text="Response (preview)")
        self._step5_requests_tree.column("job", width=52, stretch=False, anchor="e")
        self._step5_requests_tree.column("verse", width=64, stretch=False, anchor="center")
        self._step5_requests_tree.column("status", width=88, stretch=False, anchor="w")
        self._step5_requests_tree.column("progress", width=220, stretch=True, anchor="w")
        self._step5_requests_tree.column("request", width=260, stretch=True, anchor="w")
        self._step5_requests_tree.column("response", width=260, stretch=True, anchor="w")
        req_sv = ttk.Scrollbar(
            req_inner, orient=VERTICAL, command=self._step5_requests_tree.yview
        )
        req_sh = ttk.Scrollbar(
            req_inner, orient=HORIZONTAL, command=self._step5_requests_tree.xview
        )
        self._step5_requests_tree.configure(
            yscrollcommand=req_sv.set, xscrollcommand=req_sh.set
        )
        self._step5_requests_tree.bind(
            "<<TreeviewSelect>>", self._on_step5_request_log_select, add=True
        )

        self._step5_llm_response_html_cache: str | None = None
        self._step5_llm_response_outer = ttk.Labelframe(
            req_inner,
            text="API response — structured view",
            padding=(6, 6),
        )
        resp_btn = ttk.Frame(self._step5_llm_response_outer)
        resp_btn.pack(fill="x", pady=(0, 6))
        ttk.Button(
            resp_btn,
            text="Open HTML in browser",
            command=self._step5_llm_response_open_browser,
            width=22,
        ).pack(side=tk.LEFT)
        ttk.Button(
            resp_btn,
            text="Copy HTML",
            command=self._step5_llm_response_copy_html,
            width=14,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            resp_btn,
            text="Full request / raw dumps remain in the selection detail panel below.",
            font=(lf, 8),
            foreground=MaterialColors.on_surface_variant,
        ).pack(side=tk.LEFT, padx=(12, 0))
        resp_body = ttk.Frame(self._step5_llm_response_outer)
        resp_body.pack(fill=BOTH, expand=True)
        self._step5_llm_response_text = tk.Text(
            resp_body,
            height=12,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        style_tk_text_readonly(self._step5_llm_response_text, family=lf, size=9)
        r_sb = ttk.Scrollbar(resp_body, orient=VERTICAL, command=self._step5_llm_response_text.yview)
        self._step5_llm_response_text.configure(yscrollcommand=r_sb.set)
        self._step5_llm_response_text.pack(side=LEFT, fill=BOTH, expand=True)
        r_sb.pack(side=RIGHT, fill="y")

        self._step5_requests_tree.grid(row=0, column=0, sticky="nsew")
        req_sv.grid(row=0, column=1, sticky="ns")
        req_sh.grid(row=1, column=0, sticky="ew")
        self._step5_llm_response_outer.grid(row=2, column=0, columnspan=2, sticky="nsew")
        req_inner.rowconfigure(0, weight=1)
        req_inner.rowconfigure(2, weight=0)
        req_inner.columnconfigure(0, weight=1)
        self._step5_llm_response_outer.grid_remove()

        cols = ("id", "verse", "score", "tokens", "cost", "provider", "model", "created")
        tr = ttk.Frame(tab)
        tr.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))
        self._step5_results_tree = ttk.Treeview(
            tr,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=10,
        )
        self._step5_results_tree.heading("id", text="#")
        self._step5_results_tree.heading("verse", text="Verse")
        self._step5_results_tree.heading("score", text="Score")
        self._step5_results_tree.heading("tokens", text="Tokens")
        self._step5_results_tree.heading("cost", text="Cost (USD)")
        self._step5_results_tree.heading("provider", text="Provider")
        self._step5_results_tree.heading("model", text="Model")
        self._step5_results_tree.heading("created", text="Created")
        self._step5_results_tree.column("id", width=44, stretch=False, anchor="e")
        self._step5_results_tree.column("verse", width=70, stretch=False, anchor="center")
        self._step5_results_tree.column("score", width=64, stretch=False, anchor="center")
        self._step5_results_tree.column("tokens", width=86, stretch=False, anchor="e")
        self._step5_results_tree.column("cost", width=94, stretch=False, anchor="e")
        self._step5_results_tree.column("provider", width=78, stretch=False, anchor="w")
        self._step5_results_tree.column("model", width=180, stretch=True, anchor="w")
        self._step5_results_tree.column("created", width=150, stretch=False, anchor="w")
        sv = ttk.Scrollbar(tr, orient=VERTICAL, command=self._step5_results_tree.yview)
        sh = ttk.Scrollbar(tr, orient=HORIZONTAL, command=self._step5_results_tree.xview)
        self._step5_results_tree.configure(yscrollcommand=sv.set, xscrollcommand=sh.set)
        self._step5_results_tree.grid(row=0, column=0, sticky="nsew")
        sv.grid(row=0, column=1, sticky="ns")
        sh.grid(row=1, column=0, sticky="ew")
        tr.rowconfigure(0, weight=1)
        tr.columnconfigure(0, weight=1)
        self._step5_results_tree.bind("<<TreeviewSelect>>", self._on_step5_result_select, add=True)

        detail_lf = ttk.Labelframe(
            tab,
            text="Selection detail (shortlist, synthesis summary, or LLM request row)",
            padding=(6, 6),
        )
        detail_lf.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))
        self._step5_detail_text = tk.Text(
            detail_lf,
            height=11,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        style_tk_text_readonly(self._step5_detail_text, family=lf, size=9)
        dsb = ttk.Scrollbar(detail_lf, orient=VERTICAL, command=self._step5_detail_text.yview)
        self._step5_detail_text.configure(yscrollcommand=dsb.set)
        self._step5_detail_text.pack(side=LEFT, fill=BOTH, expand=True)
        dsb.pack(side=RIGHT, fill="y")

        self._refresh_step5_tab()

    def _on_step5_provider_change(self, _event: tk.Event | None = None) -> None:
        self._sync_step5_model_options()

    def _step5_model_choices_for_provider(self, provider: str) -> tuple[str, ...]:
        p = (provider or "").strip().lower()
        if p == "deepseek":
            return _STEP5_DEEPSEEK_MODEL_CHOICES
        if p == "openrouter":
            return _STEP5_OPENROUTER_MODEL_CHOICES
        return RESPONSES_TOOL_MODEL_CHOICES

    def _sync_step5_model_options(self) -> None:
        if not hasattr(self, "_step5_model_combo"):
            return
        provider = self._step5_provider_var.get().strip().lower()
        current = self._step5_model_var.get().strip()
        choices = self._step5_model_choices_for_provider(provider)
        self._step5_model_combo.configure(values=choices)
        if current in choices:
            return
        default = default_model_for_provider(provider)
        if default not in choices and choices:
            default = choices[0]
        self._step5_model_var.set(default)

    def _on_step5_all_toggle(self) -> None:
        st = "disabled" if self._step5_all_verses_var.get() else "normal"
        if hasattr(self, "_step5_verse_n_entry"):
            self._step5_verse_n_entry.configure(state=st)

    def _collect_step5_ui_settings(self) -> Step5UiSettings:
        try:
            rel_save = max(1, min(100, int((self._step5_relevance_pct_var.get() or "70").strip())))
        except ValueError:
            rel_save = 70
        try:
            vn = max(1, int(self._step5_verse_n_var.get().strip()))
        except ValueError:
            vn = 50
        try:
            workers = max(1, min(8, int(self._step5_workers_var.get().strip() or "2")))
        except ValueError:
            workers = 2
        prov = self._step5_provider_var.get().strip().lower() or "openai"
        if prov not in {"openai", "deepseek", "openrouter"}:
            prov = "openai"
        smode = "loaded" if self._step5_loaded_request_var.get() else "combination"
        s_method = self._step5_shortlist_method_var.get().strip().lower()
        if s_method not in {"cross_encoder", "llm"}:
            s_method = "cross_encoder"
        s_lprov = self._step5_shortlist_llm_provider_var.get().strip().lower()
        if s_lprov not in {"deepseek", "openai", "openrouter"}:
            s_lprov = "deepseek"
        return Step5UiSettings(
            provider=prov,
            model=self._step5_model_var.get().strip(),
            all_verses=bool(self._step5_all_verses_var.get()),
            verse_n=vn,
            max_workers=workers,
            relevance_threshold_pct=rel_save,
            use_shortlist_for_synthesis=bool(self._step5_use_shortlist_var.get()),
            synthesis_mode=smode,
            shortlist_method=s_method,
            shortlist_llm_provider=s_lprov,
            shortlist_llm_model=self._step5_shortlist_llm_model_var.get().strip(),
        )

    def _update_step5_shortlist_help_text(self) -> None:
        if not hasattr(self, "_step5_shortlist_help_var"):
            return
        if self._step5_shortlist_method_var.get().strip().lower() == "llm":
            self._step5_shortlist_help_var.set(
                "SHORTLIST keeps rows with LLM score ≥ N÷10 (batched Chat Completions). "
                "Uses the SHORTLIST LLM row (not synthesis provider). "
                "DeepSeek: «deepseek-v3.2» maps to official deepseek-chat (V3-class). "
                "OpenRouter: set OPENROUTER_API_KEY (model ids like deepseek/deepseek-v3.2). "
                "Otherwise set DEEPSEEK_API_KEY or OPENAI_API_KEY."
            )
        else:
            self._step5_shortlist_help_var.set(
                "SHORTLIST keeps rows with CrossEncoder score ≥ N÷10. "
                "Requires pip install sentence-transformers. Model: env STEP5_CROSS_ENCODER_MODEL."
            )

    def _on_step5_shortlist_method_change(self, _event: tk.Event | None = None) -> None:
        use_llm = self._step5_shortlist_method_var.get().strip().lower() == "llm"
        st: str = "normal" if use_llm else "disabled"
        if hasattr(self, "_step5_shortlist_llm_provider_combo"):
            self._step5_shortlist_llm_provider_combo.configure(state=st)
            self._step5_shortlist_llm_model_combo.configure(state=st)
        self._update_step5_shortlist_help_text()

    def _step5_shortlist_llm_model_choices_for_provider(self, provider: str) -> tuple[str, ...]:
        p = (provider or "").strip().lower()
        if p == "deepseek":
            return _STEP5_DEEPSEEK_MODEL_CHOICES
        if p == "openrouter":
            return _STEP5_OPENROUTER_MODEL_CHOICES
        return RESPONSES_TOOL_MODEL_CHOICES

    def _sync_step5_shortlist_model_options(self) -> None:
        if not hasattr(self, "_step5_shortlist_llm_model_combo"):
            return
        prov = self._step5_shortlist_llm_provider_var.get().strip().lower()
        current = self._step5_shortlist_llm_model_var.get().strip()
        choices = self._step5_shortlist_llm_model_choices_for_provider(prov)
        self._step5_shortlist_llm_model_combo.configure(values=choices)
        if current in choices:
            return
        default = default_shortlist_llm_model(prov)
        if default not in choices and choices:
            default = choices[0]
        self._step5_shortlist_llm_model_var.set(default)

    def _on_step5_shortlist_llm_provider_change(self, _event: tk.Event | None = None) -> None:
        self._sync_step5_shortlist_model_options()

    def _step5_current_refined_question(self, sid: str) -> str | None:
        try:
            conn = connect(get_db_path())
            try:
                q = refined_question_text_for_session(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            q = None
        if q and q.strip():
            return q.strip()
        sess = self._store.get(sid)
        if not sess:
            return None
        for m in reversed(sess.messages):
            if m.role == "assistant":
                j = extract_refined_json(m.content)
                if j and str(j.get("question") or "").strip():
                    return str(j.get("question") or "").strip()
                q2 = extract_refined_question(m.content)
                if q2 and q2.strip():
                    return q2.strip()
        return None

    def _run_step5_shortlist(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        q = self._step5_current_refined_question(sid)
        if not q:
            messagebox.showinfo(
                "Step 5",
                "No refined/finalized question found for this session. Complete Question refiner first.",
                parent=self._root,
            )
            return
        all_rows = bool(self._step5_all_verses_var.get())
        verse_n: int | None = None
        if not all_rows:
            try:
                verse_n = max(1, int(self._step5_verse_n_var.get().strip()))
            except ValueError:
                messagebox.showerror("Step 5", "Verse count must be a positive integer.", parent=self._root)
                return
        try:
            rel_raw = (self._step5_relevance_pct_var.get() or "").strip()
            relevance_threshold_pct = int(rel_raw) if rel_raw else 0
        except ValueError:
            messagebox.showerror(
                "Step 5",
                "Min relevance N% must be an integer 1–100 for SHORTLIST.",
                parent=self._root,
            )
            return
        relevance_threshold_pct = max(1, min(100, relevance_threshold_pct))
        method = self._step5_shortlist_method_var.get().strip().lower()
        if method not in {"cross_encoder", "llm"}:
            method = "cross_encoder"
        llm_cfg: LlmProviderConfig | None = None
        if method == "cross_encoder":
            from src.chat.step5_relevance import cross_encoder_dependencies_available

            if not cross_encoder_dependencies_available():
                messagebox.showerror(
                    "Step 5",
                    "SHORTLIST (CrossEncoder) requires sentence-transformers (also installs PyTorch).\n"
                    "Install: pip install sentence-transformers",
                    parent=self._root,
                )
                return
        else:
            s_lp = self._step5_shortlist_llm_provider_var.get().strip().lower()
            if s_lp not in {"deepseek", "openai", "openrouter"}:
                s_lp = "deepseek"
            s_lm = (
                self._step5_shortlist_llm_model_var.get().strip()
                or default_shortlist_llm_model(s_lp)
            )
            try:
                llm_cfg = resolve_provider_config(s_lp, s_lm or None)
            except LlmProviderError as e:
                messagebox.showerror("Step 5", str(e), parent=self._root)
                return

        dbp = get_db_path()
        try:
            conn = connect(dbp)
            try:
                max_rows = None if all_rows else verse_n
                matches = list_step5_matches_for_session(conn, sid, max_rows=max_rows)
                if not matches:
                    messagebox.showinfo(
                        "Step 5",
                        "No saved Find Verses rows were found for this session. Run Step 3 first.",
                        parent=self._root,
                    )
                    return
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 5", f"Database error: {e}", parent=self._root)
            return

        if method == "cross_encoder":
            busy_msg = (
                "Step 5: SHORTLIST — CrossEncoder scoring (first run may download the model)…"
            )
        else:
            busy_msg = "Step 5: SHORTLIST — LLM batched scoring…"
        self._begin_busy(busy_msg, op="step5_shortlist")
        threading.Thread(
            target=self._step5_shortlist_worker,
            args=(sid, q, matches, relevance_threshold_pct, dbp, len(matches), method, llm_cfg),
            daemon=True,
        ).start()

    def _step5_shortlist_worker(
        self,
        sid: str,
        refined_q: str,
        matches: list[Step5MatchRow],
        relevance_threshold_pct: int,
        dbp: object,
        n_source_rows: int,
        method: str,
        llm_cfg: LlmProviderConfig | None,
    ) -> None:
        err: BaseException | None = None
        cancelled = False
        entries: list[tuple[int, float]] | None = None
        model_name: str | None = None
        raw_scores: list[float] = []
        from src.chat.step5_relevance import Step5ShortlistCancelled, min_score_for_threshold_pct
        from src.chat.step5_shortlist_logging import get_step5_shortlist_logger

        slog = get_step5_shortlist_logger()
        try:
            if method == "llm" and llm_cfg is not None:
                from src.chat.step5_shortlist_llm import score_step5_matches_with_llm

                conn = connect(dbp)
                try:
                    raw_scores, provenance = score_step5_matches_with_llm(
                        refined_q,
                        matches,
                        conn=conn,
                        cfg=llm_cfg,
                        batch_size=8,
                        cancel_event=self._cancel_bot_work,
                        chat_session_id=sid,
                    )
                finally:
                    conn.close()
                model_name = provenance
            else:
                from src.chat.step5_relevance import (
                    configured_cross_encoder_model,
                    score_step5_matches,
                )

                conn = connect(dbp)
                try:
                    raw_scores = score_step5_matches(
                        refined_q,
                        matches,
                        batch_size=32,
                        conn=conn,
                        cancel_event=self._cancel_bot_work,
                        chat_session_id=sid,
                    )
                finally:
                    conn.close()
                model_name = f"ce:{configured_cross_encoder_model()}"
            lo = min_score_for_threshold_pct(relevance_threshold_pct)
            entries = []
            for m, s in zip(matches, raw_scores, strict=True):
                sc = float(s)
                if sc >= lo:
                    entries.append((m.find_match_id, sc))
            n_zero = sum(1 for x in raw_scores if x <= 0.0)
            slog.info(
                "SHORTLIST filter session=%s method=%s threshold_pct=%s min_score_0_10=%.4f "
                "source_rows=%s scored=%s kept=%s scores_min=%.4f scores_max=%.4f scores_mean=%.4f "
                "count_score_zero=%s",
                sid,
                method,
                relevance_threshold_pct,
                lo,
                n_source_rows,
                len(raw_scores),
                len(entries),
                min(raw_scores) if raw_scores else 0.0,
                max(raw_scores) if raw_scores else 0.0,
                (sum(raw_scores) / len(raw_scores)) if raw_scores else 0.0,
                n_zero,
            )
            if raw_scores and not entries:
                slog.warning(
                    "SHORTLIST session=%s kept=0: every score is below min_score=%.4f "
                    "(threshold N%%=%s → cutoff is N/10). If scores are mostly 0.0, check log for "
                    "API/parse failures on each batch.",
                    sid,
                    lo,
                    relevance_threshold_pct,
                )
        except Step5ShortlistCancelled:
            cancelled = True
        except BaseException as ex:  # noqa: BLE001
            err = ex

        def finish() -> None:
            if cancelled:
                self._end_busy("SHORTLIST stopped.")
                messagebox.showinfo(
                    "Step 5",
                    "SHORTLIST was stopped. The shortlist in the database was not updated.\n\n"
                    "Click SHORTLIST again to run a full scoring pass.",
                    parent=self._root,
                )
                return
            if err is not None:
                self._end_busy("SHORTLIST failed.")
                messagebox.showerror(
                    "Step 5",
                    f"SHORTLIST failed:\n{err}",
                    parent=self._root,
                )
                return
            assert entries is not None
            try:
                conn = connect(dbp)
                try:
                    replace_step5_session_shortlist(
                        conn,
                        sid,
                        entries,
                        threshold_pct=relevance_threshold_pct,
                        cross_encoder_model=model_name,
                    )
                finally:
                    conn.close()
            except (OSError, sqlite3.Error, ValueError) as e:
                self._end_busy("SHORTLIST DB error.")
                messagebox.showerror("Step 5", f"Database error: {e}", parent=self._root)
                return
            self._end_busy("SHORTLIST finished.")
            try:
                save_step5_ui_settings(self._collect_step5_ui_settings())
            except (OSError, TypeError, ValueError):
                pass
            self._refresh_step5_shortlist_tree()
            n_kept = len(entries)
            log_path = shortlist_log_file_path()
            if n_kept == 0:
                msg = (
                    f"SHORTLIST kept 0 of {n_source_rows} scored verse row(s). "
                    f"Cutoff: min score ≥ {relevance_threshold_pct / 10.0:.1f} on 0–10 "
                    f"(your N% = {relevance_threshold_pct}).\n\n"
                    f"Diagnostic log:\n{log_path}\n\n"
                    "In the log, check for:\n"
                    "• API errors (DeepSeek/OpenAI),\n"
                    "• parse / find_match_id mismatches (model JSON wrong),\n"
                    "• batch OK lines with scores — if all below cutoff, verses were filtered correctly."
                )
                messagebox.showwarning("Step 5 — SHORTLIST", msg, parent=self._root)
            else:
                messagebox.showinfo(
                    "Step 5",
                    f"SHORTLIST kept {n_kept} of {n_source_rows} scored verse row(s) "
                    f"(min score ≥ {relevance_threshold_pct / 10.0:.1f} on 0–10). "
                    "Review the list, then run Step 5 when ready.\n\n"
                    f"(SHORTLIST diagnostics: {log_path})",
                    parent=self._root,
                )

        self._root.after(0, finish)

    def _refresh_step5_shortlist_tree(self) -> None:
        if not hasattr(self, "_step5_shortlist_tree"):
            return
        tv = self._step5_shortlist_tree
        for iid in tv.get_children():
            tv.delete(iid)
        sid = self._current_id
        if not sid:
            self._step5_shortlist_status_var.set("Select a session to view the shortlist.")
            return
        try:
            conn = connect(get_db_path())
            try:
                rows = fetch_step5_shortlist_rows(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            self._step5_shortlist_status_var.set(f"Shortlist DB error: {e}")
            return
        if not rows:
            self._step5_shortlist_status_var.set(
                "Shortlist empty — click SHORTLIST (uses Step 3 rows and Min relevance N%)."
            )
            return
        th = rows[0].threshold_pct
        self._step5_shortlist_status_var.set(
            f"{len(rows)} verse row(s) in shortlist (SHORTLIST threshold {th}%)."
        )
        for r in rows:
            qshort = r.query_text.replace("\n", " ").strip()
            if len(qshort) > 120:
                qshort = qshort[:117] + "…"
            tv.insert(
                "",
                END,
                iid=f"step5s_{r.find_match_id}",
                values=(f"{r.surah_no}:{r.ayah_no}", f"{r.relevance_score:.2f}", qshort),
            )

    def _on_step5_shortlist_select(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "_step5_shortlist_tree") or not hasattr(self, "_step5_detail_text"):
            return
        self._hide_step5_llm_response_panel()
        tv = self._step5_shortlist_tree
        sel = tv.selection()
        if not sel:
            return
        iid = sel[0]
        if not str(iid).startswith("step5s_"):
            return
        try:
            fid = int(str(iid).split("_", 1)[1])
        except (IndexError, ValueError):
            return
        sid = self._current_id
        if not sid:
            return
        try:
            conn = connect(get_db_path())
            try:
                rows = fetch_step5_shortlist_rows(conn, sid)
                _thr, rel_meta_model = fetch_step5_shortlist_run_meta(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            text = f"DB error: {e}"
        else:
            row = next((x for x in rows if x.find_match_id == fid), None)
            if row is None:
                text = "(Shortlist row not found.)"
            else:
                meta_line = (
                    f"Scorer: {rel_meta_model}\n" if rel_meta_model else ""
                )
                text = (
                    f"Find match id: {row.find_match_id}\n"
                    f"Verse: {row.surah_no}:{row.ayah_no}\n"
                    f"Relevance score (0–10): {row.relevance_score:.3f}\n"
                    f"{meta_line}"
                    f"SHORTLIST threshold: {row.threshold_pct}%\n\n"
                    f"Query:\n{row.query_text}\n\n"
                    f"Verse text:\n{row.verse_text}\n"
                )
        tw = self._step5_detail_text
        tw.configure(state="normal")
        tw.delete("1.0", END)
        tw.insert("1.0", text)
        tw.configure(state="disabled")

    def _clear_step5_synthesis(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        if not messagebox.askyesno(
            "Step 5 — CLEAR",
            "Delete all Step 5 synthesis runs for this session from the database?\n\n"
            "This removes manifests, queued jobs, and LLM results. "
            "Find Verses data and the SHORTLIST are not removed.",
            parent=self._root,
        ):
            return
        try:
            conn = connect(get_db_path())
            try:
                n = delete_step5_synthesis_for_session(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 5", f"Database error: {e}", parent=self._root)
            return
        self._step5_run_id_by_session.pop(sid, None)
        self._refresh_step5_tab()
        messagebox.showinfo(
            "Step 5",
            f"Removed {n} synthesis run record(s) for this session.",
            parent=self._root,
        )

    def _run_step5_pipeline(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        q = self._step5_current_refined_question(sid)
        if not q:
            messagebox.showinfo(
                "Step 5",
                "No refined/finalized question found for this session. Complete Question refiner first.",
                parent=self._root,
            )
            return
        provider = self._step5_provider_var.get().strip().lower() or "openai"
        model = self._step5_model_var.get().strip()
        all_rows = bool(self._step5_all_verses_var.get())
        verse_n: int | None = None
        if not all_rows:
            try:
                verse_n = max(1, int(self._step5_verse_n_var.get().strip()))
            except ValueError:
                messagebox.showerror("Step 5", "Verse count must be a positive integer.", parent=self._root)
                return
        try:
            workers = max(1, min(8, int(self._step5_workers_var.get().strip() or "2")))
        except ValueError:
            messagebox.showerror("Step 5", "Workers must be an integer between 1 and 8.", parent=self._root)
            return
        use_shortlist_only = bool(self._step5_use_shortlist_var.get())
        try:
            cfg = resolve_provider_config(provider, model or None)
        except LlmProviderError as e:
            messagebox.showerror("Step 5", str(e), parent=self._root)
            return
        s5_core: str | None
        if hasattr(self, "_step5_sys_core"):
            s5_core = self._step5_sys_core.get("1.0", END).rstrip()
        else:
            s5_core = None
        try:
            system_prompt = load_step5_system_prompt(instructions_base=s5_core)
        except (OSError, FileNotFoundError, ValueError) as e:
            messagebox.showerror("Step 5", str(e), parent=self._root)
            return

        dbp = get_db_path()
        relevance_by_find_match_id: dict[int, float] | None = None
        rel_meta_thr: int | None = None
        rel_meta_model: str | None = None
        confirm_prefix: str | None = None
        try:
            conn = connect(dbp)
            try:
                if use_shortlist_only:
                    ids = fetch_step5_shortlist_find_match_ids(conn, sid)
                    if not ids:
                        messagebox.showinfo(
                            "Step 5",
                            "Shortlist is empty. Click SHORTLIST to score and filter verses, "
                            'or uncheck "Run Step 5 on shortlisted verses only" to use all Step 3 rows.',
                            parent=self._root,
                        )
                        return
                    matches = list_step5_matches_for_session(
                        conn, sid, max_rows=None, only_find_match_ids=ids
                    )
                    relevance_by_find_match_id = fetch_step5_shortlist_scores_map(conn, sid)
                    rel_meta_thr, rel_meta_model = fetch_step5_shortlist_run_meta(conn, sid)
                    confirm_prefix = (
                        f"Synthesis will use {len(matches)} shortlisted verse row(s) only.\n\n"
                    )
                else:
                    max_rows = None if all_rows else verse_n
                    matches = list_step5_matches_for_session(conn, sid, max_rows=max_rows)
                if not matches:
                    messagebox.showinfo(
                        "Step 5",
                        "No saved Find Verses rows were found for this session. Run Step 3 first.",
                        parent=self._root,
                    )
                    return
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 5", f"Database error: {e}", parent=self._root)
            return

        self._step5_continue_after_matches(
            sid=sid,
            refined_q=q,
            matches=matches,
            relevance_by_find_match_id=relevance_by_find_match_id,
            relevance_threshold_pct=rel_meta_thr or 0,
            cross_encoder_model=rel_meta_model,
            dbp=dbp,
            cfg=cfg,
            system_prompt=system_prompt,
            workers=workers,
            all_rows=all_rows,
            verse_n=verse_n,
            confirm_prefix=confirm_prefix,
        )

    def _step5_continue_after_matches(
        self,
        *,
        sid: str,
        refined_q: str,
        matches: list[Step5MatchRow],
        relevance_by_find_match_id: dict[int, float] | None,
        relevance_threshold_pct: int,
        cross_encoder_model: str | None,
        dbp: object,
        cfg: LlmProviderConfig,
        system_prompt: str,
        workers: int,
        all_rows: bool,
        verse_n: int | None,
        confirm_prefix: str | None = None,
    ) -> None:
        loaded_mode = bool(self._step5_loaded_request_var.get())
        synthesis_mode = "loaded" if loaded_mode else "combination"
        run_id: int | None = None
        total_combos = 0
        inserted = 0
        try:
            conn = connect(dbp)
            try:
                run_id = create_step5_run(
                    conn,
                    chat_session_id=sid,
                    provider=cfg.provider,
                    model=cfg.model,
                    verse_mode="all" if all_rows else "first_n",
                    verse_n=verse_n,
                    system_prompt_hash=system_prompt_sha256(system_prompt),
                    relevance_threshold_pct=(
                        relevance_threshold_pct if relevance_threshold_pct > 0 else None
                    ),
                    cross_encoder_model=(
                        cross_encoder_model if relevance_threshold_pct > 0 else None
                    ),
                    synthesis_mode=synthesis_mode,
                )
                for m in matches:
                    manifest = build_verse_manifest(conn, find_match_id=m.find_match_id)
                    if manifest.total_combos <= 0:
                        continue
                    ce = None
                    if relevance_by_find_match_id is not None:
                        ce = relevance_by_find_match_id.get(m.find_match_id)
                    per_manifest_jobs = 1 if loaded_mode else manifest.total_combos
                    insert_step5_manifest(
                        conn,
                        run_id=run_id,
                        find_match_id=m.find_match_id,
                        bot1_topic_id=m.bot1_topic_id,
                        bot1_connotation_id=m.bot1_connotation_id,
                        surah_no=m.surah_no,
                        ayah_no=m.ayah_no,
                        verse_text=m.verse_text,
                        manifest_json=manifest_to_json(manifest),
                        total_combos=per_manifest_jobs,
                        cross_encoder_relevance=ce,
                    )
                    total_combos += per_manifest_jobs
                    inserted += 1
            finally:
                conn.close()
        except (OSError, sqlite3.Error, ValueError) as e:
            messagebox.showerror("Step 5", f"Database error: {e}", parent=self._root)
            return

        if inserted <= 0 or total_combos <= 0:
            messagebox.showinfo(
                "Step 5",
                "No valid morpheme-root Lane-entry combinations were found to process.",
                parent=self._root,
            )
            return

        prefix = confirm_prefix or ""
        if loaded_mode:
            confirm_msg = (
                prefix
                + f"Start Step 5 run with {inserted} verse row(s) and {inserted} loaded request(s) "
                "(one LLM call per verse, all Lane entries)?"
            )
        else:
            confirm_msg = (
                prefix
                + f"Start Step 5 run with {inserted} verse row(s) and {total_combos} combination job(s)?"
            )
        if not messagebox.askyesno("Step 5", confirm_msg, parent=self._root):
            return

        try:
            conn = connect(dbp)
            try:
                bulk_seed_step5_jobs_for_run(conn, run_id)
            finally:
                conn.close()
        except (OSError, sqlite3.Error, ValueError) as e:
            messagebox.showerror(
                "Step 5",
                f"Could not prepare job queue in the database: {e}",
                parent=self._root,
            )
            return

        save_step5_ui_settings(self._collect_step5_ui_settings())

        assert run_id is not None
        self._step5_run_id_by_session[sid] = run_id
        try:
            self._refresh_step5_tab()
            self._root.update_idletasks()
        except tk.TclError:
            pass
        self._step5_orchestrator = Step5Orchestrator(
            db_path=dbp,
            run_id=run_id,
            chat_session_id=sid,
            question_text=refined_q,
            provider_cfg=cfg,
            system_prompt=system_prompt,
            max_workers=workers,
            batch_size=20,
            cancel_event=self._cancel_bot_work,
            on_status=lambda msg: self._root.after(0, lambda: self._status.set(msg)),
            on_after_job_db_write=self._schedule_step5_live_refresh,
            synthesis_mode=synthesis_mode,
        )
        self._pipeline_step_start(sid, 5)
        self._begin_busy("Running Step 5…", op="step5")
        self._step5_last_heavy_refresh_mono = None
        self._step5_orchestrator.start()
        self._schedule_step5_poll()

    def _resume_step5_pipeline(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        dbp = get_db_path()
        try:
            conn = connect(dbp)
            try:
                run_id = latest_step5_run_id_for_session(conn, sid)
                if run_id is None:
                    messagebox.showinfo(
                        "Step 5",
                        "No Step 5 run exists for this session yet.",
                        parent=self._root,
                    )
                    return
                if not step5_run_is_resumable(conn, run_id):
                    messagebox.showinfo(
                        "Step 5",
                        "The latest Step 5 run is already finished or was cancelled — "
                        "nothing to resume.",
                        parent=self._root,
                    )
                    return
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 5", f"Database error: {e}", parent=self._root)
            return

        q = self._step5_current_refined_question(sid)
        if not q:
            messagebox.showinfo(
                "Step 5",
                "No refined/finalized question found for this session. Complete Question refiner first.",
                parent=self._root,
            )
            return
        provider = self._step5_provider_var.get().strip().lower() or "openai"
        model = self._step5_model_var.get().strip()
        try:
            workers = max(1, min(8, int(self._step5_workers_var.get().strip() or "2")))
        except ValueError:
            messagebox.showerror("Step 5", "Workers must be an integer between 1 and 8.", parent=self._root)
            return
        try:
            cfg = resolve_provider_config(provider, model or None)
        except LlmProviderError as e:
            messagebox.showerror("Step 5", str(e), parent=self._root)
            return
        s5_core: str | None
        if hasattr(self, "_step5_sys_core"):
            s5_core = self._step5_sys_core.get("1.0", END).rstrip()
        else:
            s5_core = None
        try:
            system_prompt = load_step5_system_prompt(instructions_base=s5_core)
        except (OSError, FileNotFoundError, ValueError) as e:
            messagebox.showerror("Step 5", str(e), parent=self._root)
            return

        loaded_mode = bool(self._step5_loaded_request_var.get())
        synthesis_mode = "loaded" if loaded_mode else "combination"
        self._step5_run_id_by_session[sid] = run_id
        try:
            self._refresh_step5_tab()
            self._root.update_idletasks()
        except tk.TclError:
            pass
        if self._step5_orchestrator is not None and self._step5_orchestrator.is_running:
            messagebox.showinfo(
                "Step 5",
                "Step 5 is already running.",
                parent=self._root,
            )
            return

        if not messagebox.askyesno(
            "Step 5 — Resume",
            f"Resume synthesis for run id {run_id}?\n\n"
            "Any jobs stuck in in_progress (e.g. after a crash) will be reset to waiting_retry. "
            "Uses the current provider, model, workers, and system instructions above.",
            parent=self._root,
        ):
            return

        try:
            conn2 = connect(dbp)
            try:
                n_stale = reset_stale_step5_in_progress_jobs(conn2, run_id)
            finally:
                conn2.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Step 5", f"Database error: {e}", parent=self._root)
            return
        if n_stale > 0:
            self._status.set(f"Step 5 resume: reset {n_stale} stale job(s).")

        self._step5_orchestrator = Step5Orchestrator(
            db_path=dbp,
            run_id=run_id,
            chat_session_id=sid,
            question_text=q,
            provider_cfg=cfg,
            system_prompt=system_prompt,
            max_workers=workers,
            batch_size=20,
            cancel_event=self._cancel_bot_work,
            on_status=lambda msg: self._root.after(0, lambda: self._status.set(msg)),
            on_after_job_db_write=self._schedule_step5_live_refresh,
            synthesis_mode=synthesis_mode,
        )
        self._begin_busy("Resuming Step 5…", op="step5")
        self._step5_last_heavy_refresh_mono = None
        self._step5_orchestrator.start()
        self._schedule_step5_poll()

    def _schedule_bot2_dependent_refresh(self) -> None:
        """Debounced refresh after incremental Bot 2 DB writes (worker threads)."""

        def _flush() -> None:
            self._bot2_refresh_after_id = None
            try:
                self._refresh_bot_dependent_tabs()
            except tk.TclError:
                pass

        try:
            if self._bot2_refresh_after_id is not None:
                self._root.after_cancel(self._bot2_refresh_after_id)
            self._bot2_refresh_after_id = self._root.after(120, _flush)
        except tk.TclError:
            pass

    def _schedule_step5_live_refresh(self) -> None:
        """Called from Step 5 worker threads after DB writes; debounces Tk refreshes."""

        def _flush() -> None:
            self._step5_live_refresh_after_id = None
            try:
                self._refresh_step5_tab()
            except tk.TclError:
                pass

        try:
            if self._step5_live_refresh_after_id is not None:
                self._root.after_cancel(self._step5_live_refresh_after_id)
            orch = self._step5_orchestrator
            delay_ms = 750 if (orch is not None and orch.is_running) else 40
            self._step5_live_refresh_after_id = self._root.after(delay_ms, _flush)
        except tk.TclError:
            pass

    def _schedule_step5_poll(self) -> None:
        if self._step5_poll_after_id is not None:
            try:
                self._root.after_cancel(self._step5_poll_after_id)
            except tk.TclError:
                pass
            self._step5_poll_after_id = None
        orch = self._step5_orchestrator
        delay_ms = 500 if (orch is not None and orch.is_running) else 100
        self._step5_poll_after_id = self._root.after(delay_ms, self._poll_step5_progress)

    @staticmethod
    def _fmt_step5_count(n: int) -> str:
        """Readable counter for huge Step 5 job totals."""
        if n >= 10**15:
            return f"{float(n):.3e}"
        return str(int(n))

    @staticmethod
    def _format_step5_request_stats(st: Step5RequestStats) -> str:
        t = st.total_requests
        d = st.done
        if t <= 0:
            return "LLM requests: — (no job rows for this run in the database yet)"
        pct = (100 * d) // t if t else 0
        parts = [
            f"Total LLM requests: {t}",
            f"Done: {d} ({pct}%)",
        ]
        if st.in_progress:
            parts.append(f"In progress: {st.in_progress}")
        if st.failed:
            parts.append(f"Failed: {st.failed}")
        if st.waiting_retry:
            parts.append(f"Waiting retry: {st.waiting_retry}")
        if st.cancelled:
            parts.append(f"Cancelled: {st.cancelled}")
        return " · ".join(parts)

    def _clear_step5_run_stats_panel(self) -> None:
        if hasattr(self, "_step5_stats_chart_holder"):
            for w in self._step5_stats_chart_holder.winfo_children():
                w.destroy()
        self._step5_stats_mpl_canvas = None
        for attr in (
            "_step5_stat_saved_rows",
            "_step5_stat_distinct_verses",
            "_step5_stat_llm_requests",
            "_step5_stat_tokens_in",
            "_step5_stat_tokens_out",
            "_step5_stat_tokens_total",
            "_step5_stat_tokens_avg",
            "_step5_stat_cost",
            "_step5_stat_cost_avg",
            "_step5_stat_scores",
            "_step5_stat_job_mix",
            "_step5_stat_manifest_prog",
            "_step5_stat_failures",
        ):
            if hasattr(self, attr):
                getattr(self, attr).set("—")

    def _apply_step5_run_stats_scorecard(
        self,
        *,
        analytics: Step5RunAnalytics,
        st: Step5RequestStats,
        progress,
        run_id: int,
    ) -> None:
        self._step5_stat_saved_rows.set(self._fmt_step5_count(analytics.result_count))
        self._step5_stat_distinct_verses.set(self._fmt_step5_count(analytics.distinct_verse_count))
        self._step5_stat_llm_requests.set(
            f"{self._fmt_step5_count(st.total_requests)} total · "
            f"{self._fmt_step5_count(analytics.result_count)} with saved JSON result "
            f"(run #{run_id})"
        )
        self._step5_stat_tokens_in.set(self._fmt_step5_count(analytics.sum_prompt_tokens))
        self._step5_stat_tokens_out.set(self._fmt_step5_count(analytics.sum_completion_tokens))
        self._step5_stat_tokens_total.set(self._fmt_step5_count(analytics.sum_total_tokens))
        rc = analytics.result_count
        if rc > 0:
            ai = analytics.sum_prompt_tokens / rc
            ao = analytics.sum_completion_tokens / rc
            at = analytics.sum_total_tokens / rc
            self._step5_stat_tokens_avg.set(f"{ai:.1f} → {ao:.1f} → {at:.1f}")
            ac = analytics.total_cost_usd / rc
            self._step5_stat_cost_avg.set(f"${ac:.6f}")
        else:
            self._step5_stat_tokens_avg.set("— (no saved rows)")
            self._step5_stat_cost_avg.set("— (no saved rows)")
        self._step5_stat_cost.set(f"${analytics.total_cost_usd:.6f}")
        if analytics.with_score_count <= 0:
            self._step5_stat_scores.set("— (no possibility_score in saved rows)")
        else:
            avg_s = (
                f"{analytics.score_avg:.2f}"
                if analytics.score_avg is not None
                else "—"
            )
            rng = (
                f"{analytics.score_min}–{analytics.score_max}"
                if analytics.score_min is not None and analytics.score_max is not None
                else "—"
            )
            miss = (
                f", missing score: {analytics.without_score_count}"
                if analytics.without_score_count
                else ""
            )
            self._step5_stat_scores.set(
                f"avg {avg_s}, range {rng}, with score: {analytics.with_score_count}{miss}"
            )
        self._step5_stat_job_mix.set(
            f"done {self._fmt_step5_count(st.done)} · failed {self._fmt_step5_count(st.failed)} · "
            f"in progress {self._fmt_step5_count(st.in_progress)} · "
            f"retry {self._fmt_step5_count(st.waiting_retry)} · "
            f"cancelled {self._fmt_step5_count(st.cancelled)}"
        )
        self._step5_stat_manifest_prog.set(
            f"completed {self._fmt_step5_count(progress.completed)} / "
            f"{self._fmt_step5_count(progress.total_jobs)} jobs · "
            f"dispatched {self._fmt_step5_count(progress.dispatched)} · "
            f"cancelled run: {'yes' if progress.is_cancelled else 'no'}"
        )
        if analytics.failed_jobs_by_error:
            parts = [f"{code}: {n}" for code, n in analytics.failed_jobs_by_error[:5]]
            self._step5_stat_failures.set(" · ".join(parts))
        else:
            self._step5_stat_failures.set(
                "—" if st.failed == 0 else f"(no error_code rows; {st.failed} failed in queue)"
            )

    def _redraw_step5_run_stats_charts(
        self,
        *,
        analytics: Step5RunAnalytics,
        st: Step5RequestStats,
    ) -> None:
        if not hasattr(self, "_step5_stats_chart_holder"):
            return
        holder = self._step5_stats_chart_holder
        for w in holder.winfo_children():
            w.destroy()
        self._step5_stats_mpl_canvas = None
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except ImportError:
            ttk.Label(
                holder,
                text="Install matplotlib to show charts (see requirements.txt).",
                foreground=MaterialColors.on_surface_variant,
            ).pack(anchor="w", pady=6)
            return
        if st.total_requests <= 0 and analytics.result_count <= 0:
            ttk.Label(
                holder,
                text=(
                    "No Step 5 job or result rows yet for this run — charts appear after "
                    "«Run Step 5 & save to DB» completes requests."
                ),
                foreground=MaterialColors.on_surface_variant,
                wraplength=720,
                justify="left",
            ).pack(anchor="w", pady=6)
            return

        fig = Figure(figsize=(9.2, 3.45), dpi=100, facecolor=MaterialColors.surface)
        ax_pie, ax_bar = fig.subplots(1, 2)

        labels: list[str] = []
        sizes: list[float] = []
        colors: list[str] = []
        pie_spec = [
            ("Done", st.done, "#2e7d32"),
            ("Failed", st.failed, "#c62828"),
            ("In progress", st.in_progress, "#1565c0"),
            ("Waiting retry", st.waiting_retry, "#f9a825"),
            ("Cancelled", st.cancelled, "#9e9e9e"),
        ]
        for lab, sz, col in pie_spec:
            if sz > 0:
                labels.append(lab)
                sizes.append(float(sz))
                colors.append(col)
        if sizes:
            ax_pie.pie(
                sizes,
                labels=labels,
                colors=colors,
                autopct="%1.0f%%",
                startangle=90,
                textprops={"fontsize": 8},
            )
            ax_pie.set_title("Job queue by status", fontsize=10)
        else:
            ax_pie.text(
                0.5, 0.5, "No status slices", ha="center", va="center", transform=ax_pie.transAxes
            )
            ax_pie.axis("off")

        if analytics.score_histogram:
            xs = [t[0] for t in analytics.score_histogram]
            ys = [t[1] for t in analytics.score_histogram]
            ax_bar.bar(xs, ys, color="#1565c0", alpha=0.88)
            ax_bar.set_xlabel("Possibility score", fontsize=9)
            ax_bar.set_ylabel("Saved rows", fontsize=9)
            ax_bar.set_title("Score distribution (saved results)", fontsize=10)
            ax_bar.grid(axis="y", linestyle=":", alpha=0.55)
        else:
            ax_bar.text(
                0.5,
                0.5,
                "No possibility scores\nin saved results yet",
                ha="center",
                va="center",
                transform=ax_bar.transAxes,
                fontsize=9,
            )
            ax_bar.axis("off")

        fig.tight_layout()
        style_mpl_figure(fig)
        canvas = FigureCanvasTkAgg(fig, master=holder)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)
        self._step5_stats_mpl_canvas = canvas
        if hasattr(self, "_qr_sync_scrollregion"):
            self._root.after_idle(self._qr_sync_scrollregion)

    def _save_step5_stats_snapshot(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            messagebox.showinfo("Step 5", "Select a session first.", parent=self._root)
            return
        try:
            conn = connect(get_db_path())
            try:
                run_id = self._step5_run_id_by_session.get(sid)
                if run_id is None:
                    run_id = latest_step5_run_id_for_session(conn, sid)
                if run_id is None:
                    messagebox.showinfo(
                        "Step 5",
                        "No Step 5 run found for this session.",
                        parent=self._root,
                    )
                    return
                analytics = fetch_step5_run_analytics(conn, run_id)
                st = fetch_step5_request_stats(conn, run_id)
                progress = fetch_step5_progress(conn, run_id)
                payload = {
                    "schema_version": 1,
                    "run_id": int(run_id),
                    "session_id": sid,
                    "metrics_summary": {
                        "llm_requests_total": st.total_requests,
                        "llm_requests_done": st.done,
                        "llm_requests_failed": st.failed,
                        "llm_requests_in_progress": st.in_progress,
                        "llm_requests_waiting_retry": st.waiting_retry,
                        "llm_requests_cancelled": st.cancelled,
                        "saved_result_rows": analytics.result_count,
                        "distinct_verses": analytics.distinct_verse_count,
                        "tokens_input_prompt": analytics.sum_prompt_tokens,
                        "tokens_output_completion": analytics.sum_completion_tokens,
                        "tokens_total": analytics.sum_total_tokens,
                        "avg_tokens_input_per_saved_result": (
                            analytics.sum_prompt_tokens / analytics.result_count
                            if analytics.result_count
                            else None
                        ),
                        "avg_tokens_output_per_saved_result": (
                            analytics.sum_completion_tokens / analytics.result_count
                            if analytics.result_count
                            else None
                        ),
                        "avg_tokens_total_per_saved_result": (
                            analytics.sum_total_tokens / analytics.result_count
                            if analytics.result_count
                            else None
                        ),
                        "cost_usd_total": analytics.total_cost_usd,
                        "cost_usd_avg_per_saved_result": (
                            analytics.total_cost_usd / analytics.result_count
                            if analytics.result_count
                            else None
                        ),
                        "manifest_jobs_total": progress.total_jobs,
                        "manifest_jobs_completed": progress.completed,
                        "manifest_jobs_failed": progress.failed,
                        "manifest_cost_usd_reported": progress.cost_usd,
                    },
                    "analytics": analytics.to_json_dict(),
                    "request_stats": asdict(st),
                    "progress": asdict(progress),
                }
                raw = json.dumps(payload, ensure_ascii=False, indent=2)
                snap_id = insert_step5_run_stats_snapshot(conn, run_id=run_id, stats_json=raw)
            finally:
                conn.close()
        except (OSError, sqlite3.Error, TypeError, ValueError) as e:
            messagebox.showerror("Step 5", f"Could not save stats snapshot: {e}", parent=self._root)
            return
        messagebox.showinfo(
            "Step 5",
            f"Saved stats snapshot id {snap_id} for run {run_id} (table step5_run_stats_snapshots).",
            parent=self._root,
        )

    def _poll_step5_progress(self) -> None:
        self._step5_poll_after_id = None
        orch = self._step5_orchestrator
        sid = self._current_id
        run_id = self._step5_run_id_by_session.get(sid or "", None) if sid else None
        if orch is None:
            self._refresh_step5_tab()
            if self._busy_op == "step5":
                self._end_busy("Step 5 finished.")
            return
        try:
            p = orch.get_progress()
            self._step5_progress_var.set(
                f"Run {run_id or '?'}: completed "
                f"{self._fmt_step5_count(p.completed)}/{self._fmt_step5_count(p.total_jobs)}, "
                f"failed {p.failed}, waiting retry {p.waiting_retry}, cost ${p.cost_usd:.6f}"
            )
        except Exception as e:  # noqa: BLE001
            self._step5_progress_var.set(f"Step 5 progress error: {e}")
        still_running = orch.is_running and not self._cancel_bot_work.is_set()
        if still_running:
            now = time.monotonic()
            last = getattr(self, "_step5_last_heavy_refresh_mono", None)
            if last is None or (now - float(last)) >= 1.6:
                self._step5_last_heavy_refresh_mono = now
                self._refresh_step5_tab()
        else:
            self._refresh_step5_tab()
        if still_running:
            self._schedule_step5_poll()
            return
        if self._cancel_bot_work.is_set() and run_id is not None:
            try:
                conn = connect(get_db_path())
                try:
                    cancel_step5_run(conn, run_id)
                finally:
                    conn.close()
            except (OSError, sqlite3.Error):
                pass
        self._step5_orchestrator = None
        cancelled = self._cancel_bot_work.is_set()
        if cancelled:
            if sid:
                self._pipeline_step_clock.pop((sid, 5), None)
        elif sid and run_id is not None:
            try:
                conn = connect(get_db_path())
                try:
                    analytics = fetch_step5_run_analytics(conn, run_id)
                    cin, cout, ml = fetch_step5_run_models_and_split_cost(conn, run_id)
                    tot_split = cin + cout
                    if tot_split > 1e-12 and analytics.total_cost_usd >= 0:
                        sc = analytics.total_cost_usd / tot_split
                        cin *= sc
                        cout *= sc
                    self._pipeline_step_finish_from_partial(
                        sid,
                        5,
                        agent=True,
                        in_tok=analytics.sum_prompt_tokens,
                        out_tok=analytics.sum_completion_tokens,
                        in_usd=cin,
                        out_usd=cout,
                        models=ml,
                    )
                finally:
                    conn.close()
            except (OSError, sqlite3.Error):
                if sid:
                    self._pipeline_step_clock.pop((sid, 5), None)
        self._end_busy("Step 5 stopped." if cancelled else "Step 5 finished.")

    def _refresh_step5_tab(self) -> None:
        self._refresh_step5_shortlist_tree()
        if not hasattr(self, "_step5_results_tree"):
            return
        if hasattr(self, "_step5_stat_saved_rows"):
            self._clear_step5_run_stats_panel()
        tv = self._step5_results_tree
        rtv = self._step5_requests_tree if hasattr(self, "_step5_requests_tree") else None
        saved_rq_sel: tuple[str, ...] = ()
        if rtv is not None:
            saved_rq_sel = tuple(rtv.selection())
        for iid in tv.get_children():
            tv.delete(iid)
        if rtv is not None:
            for iid in rtv.get_children():
                rtv.delete(iid)
        self._hide_step5_llm_response_panel()
        sid = self._current_id
        if not sid:
            self._step5_progress_var.set("Select or create a session.")
            self._step5_request_stats_var.set("")
            return
        rows: list = []
        req_log: list = []
        try:
            conn = connect(get_db_path())
            try:
                run_id = self._step5_run_id_by_session.get(sid)
                if run_id is None:
                    run_id = latest_step5_run_id_for_session(conn, sid)
                    if run_id is not None:
                        self._step5_run_id_by_session[sid] = run_id
                if run_id is None:
                    self._step5_progress_var.set("No Step 5 runs for this session yet.")
                    self._step5_request_stats_var.set("")
                    self._hide_step5_llm_response_panel()
                    return
                p = fetch_step5_progress(conn, run_id)
                self._step5_progress_var.set(
                    f"Run {run_id}: completed "
                    f"{self._fmt_step5_count(p.completed)}/{self._fmt_step5_count(p.total_jobs)}, "
                    f"failed {p.failed}, retry {p.waiting_retry}, cost ${p.cost_usd:.6f}"
                )
                st = fetch_step5_request_stats(conn, run_id)
                self._step5_request_stats_var.set(self._format_step5_request_stats(st))
                analytics = fetch_step5_run_analytics(conn, run_id)
                self._apply_step5_run_stats_scorecard(
                    analytics=analytics, st=st, progress=p, run_id=run_id
                )
                orch_live = getattr(self, "_step5_orchestrator", None)
                step5_busy = orch_live is not None and orch_live.is_running
                if not step5_busy:
                    self._redraw_step5_run_stats_charts(analytics=analytics, st=st)
                else:
                    now_mono = time.monotonic()
                    next_chart = getattr(self, "_step5_next_chart_redraw_mono", 0.0)
                    if now_mono >= float(next_chart):
                        self._step5_next_chart_redraw_mono = now_mono + 6.0
                        self._redraw_step5_run_stats_charts(analytics=analytics, st=st)
                rows = fetch_step5_results_for_run(conn, run_id, limit=300)
                req_log = fetch_step5_request_log_for_run(
                    conn,
                    run_id,
                    limit=1000 if step5_busy else 20000,
                    heavy_text_max_chars=512,
                    recent_tail=step5_busy,
                )
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            self._step5_progress_var.set(f"Step 5 DB error: {e}")
            self._step5_request_stats_var.set("")
            if hasattr(self, "_step5_stat_saved_rows"):
                self._clear_step5_run_stats_panel()
            return
        rq_restored = False
        if rtv is not None:
            for lr in req_log:
                rtv.insert(
                    "",
                    END,
                    iid=f"step5q_{lr.job_id}",
                    values=(
                        lr.job_id,
                        f"{lr.surah_no}:{lr.ayah_no}",
                        lr.status_label,
                        lr.progress_label,
                        lr.request_preview,
                        lr.response_preview,
                    ),
                )
            if saved_rq_sel:
                for iid in saved_rq_sel:
                    if rtv.exists(iid):
                        rtv.selection_set(iid)
                        rtv.see(iid)
                        rq_restored = True
                        break
            elif req_log:
                orch_live = getattr(self, "_step5_orchestrator", None)
                if orch_live is not None and orch_live.is_running:
                    kids = rtv.get_children()
                    if kids:
                        rtv.see(kids[-1])
        for r in rows:
            score = "" if r.possibility_score is None else str(r.possibility_score)
            tok = "" if r.total_tokens is None else str(r.total_tokens)
            cost = "" if r.cost_usd is None else f"{r.cost_usd:.6f}"
            iid = f"step5r_{r.result_id}"
            tv.insert(
                "",
                END,
                iid=iid,
                values=(
                    r.result_id,
                    f"{r.surah_no}:{r.ayah_no}",
                    score,
                    tok,
                    cost,
                    r.provider,
                    r.model,
                    r.created_at,
                ),
            )
        if rows:
            first = f"step5r_{rows[0].result_id}"
            if tv.exists(first) and not rq_restored:
                tv.selection_set(first)
                self._on_step5_result_select()
        elif not rq_restored:
            if hasattr(self, "_step5_detail_text"):
                self._step5_detail_text.configure(state="normal")
                self._step5_detail_text.delete("1.0", END)
                self._step5_detail_text.insert("1.0", "(No Step 5 results yet.)")
                self._step5_detail_text.configure(state="disabled")
        if rq_restored:
            self._on_step5_request_log_select()

    @staticmethod
    def _step5_pretty_json_or_raw(raw: str | None) -> str:
        if not raw or not str(raw).strip():
            return "(none)\n"
        s = str(raw).strip()
        try:
            return json.dumps(json.loads(s), ensure_ascii=False, indent=2) + "\n"
        except json.JSONDecodeError:
            return s + "\n"

    def _hide_step5_llm_response_panel(self) -> None:
        if hasattr(self, "_step5_llm_response_outer"):
            self._step5_llm_response_outer.grid_remove()
        self._step5_llm_response_html_cache = None

    def _fill_step5_llm_response_panel(self, row: sqlite3.Row) -> None:
        if not hasattr(self, "_step5_llm_response_text"):
            return
        lc_raw = row["llm_call_state"]
        llm_state = (
            str(lc_raw).strip() if lc_raw is not None and str(lc_raw).strip() else None
        )
        rid = row["result_id"]
        result_id = int(rid) if rid is not None else None
        ec = row["error_code"]
        em = row["error_message"]
        rj = row["response_json"]
        rt = row["raw_response_text"]
        upj = row["user_payload_json"]
        payload_s = str(upj) if upj else None
        html_doc = build_step5_llm_response_html(
            job_id=int(row["job_id"]),
            surah_no=int(row["surah_no"]),
            ayah_no=int(row["ayah_no"]),
            job_status=str(row["job_status"] or ""),
            attempt_count=int(row["attempt_count"] or 1),
            llm_call_state=llm_state,
            result_id=result_id,
            error_code=str(ec).strip() if ec else None,
            error_message=str(em).strip() if em else None,
            response_json=str(rj) if rj else None,
            raw_response_text=str(rt) if rt else None,
            user_payload_json=payload_s,
        )
        self._step5_llm_response_html_cache = html_doc
        apply_step5_response_to_tk_text(
            self._step5_llm_response_text,
            job_id=int(row["job_id"]),
            surah_no=int(row["surah_no"]),
            ayah_no=int(row["ayah_no"]),
            job_status=str(row["job_status"] or ""),
            attempt_count=int(row["attempt_count"] or 1),
            llm_call_state=llm_state,
            result_id=result_id,
            error_code=str(ec).strip() if ec else None,
            error_message=str(em).strip() if em else None,
            response_json=str(rj) if rj else None,
            raw_response_text=str(rt) if rt else None,
            latin_family=self._latin,
            arabic_family=self._arabic,
            user_payload_json=payload_s,
        )
        self._step5_llm_response_outer.grid()

    def _step5_llm_response_open_browser(self) -> None:
        html_doc = self._step5_llm_response_html_cache
        if not html_doc:
            messagebox.showinfo(
                "Step 5",
                "Select a row in «LLM API calls» first.",
                parent=self._root,
            )
            return
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".html",
                delete=False,
            ) as f:
                f.write(html_doc)
                path = f.name
            webbrowser.open(Path(path).as_uri())
        except OSError as e:
            messagebox.showerror(
                "Step 5",
                f"Could not open HTML preview: {e}",
                parent=self._root,
            )

    def _step5_llm_response_copy_html(self) -> None:
        html_doc = self._step5_llm_response_html_cache
        if not html_doc:
            messagebox.showinfo(
                "Step 5",
                "Select a row in «LLM API calls» first.",
                parent=self._root,
            )
            return
        self._root.clipboard_clear()
        self._root.clipboard_append(html_doc)

    def _on_step5_request_log_select(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "_step5_requests_tree") or not hasattr(self, "_step5_detail_text"):
            return
        tv = self._step5_requests_tree
        sel = tv.selection()
        if not sel:
            self._hide_step5_llm_response_panel()
            return
        iid = sel[0]
        if not str(iid).startswith("step5q_"):
            self._hide_step5_llm_response_panel()
            return
        try:
            job_id = int(str(iid)[len("step5q_") :])
        except ValueError:
            self._hide_step5_llm_response_panel()
            return
        try:
            conn = connect(get_db_path())
            try:
                row = fetch_step5_job_llm_detail(conn, job_id)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            text = f"DB error: {e}"
            self._hide_step5_llm_response_panel()
        else:
            if row is None:
                text = "(Job not found.)"
                self._hide_step5_llm_response_panel()
            else:
                self._fill_step5_llm_response_panel(row)
                st = str(row["job_status"] or "")
                rid = row["result_id"]
                has_res = rid is not None
                parts: list[str] = []
                parts.append(f"=== Step 5 LLM request — job {job_id} ===\n")
                parts.append(
                    f"Verse: {row['surah_no']}:{row['ayah_no']}  |  "
                    f"Job status: {st}  |  Attempts: {row['attempt_count']}\n"
                )
                lcs = row["llm_call_state"]
                if lcs is not None and str(lcs).strip():
                    parts.append(f"Live phase (llm_call_state): {lcs}\n")
                if row["error_code"] or row["error_message"]:
                    parts.append(
                        f"Error: {str(row['error_code'] or '')} "
                        f"{str(row['error_message'] or '')}\n"
                    )
                if has_res:
                    parts.append(f"Saved result id: {int(rid)}\n")
                parts.append(
                    "\n(Structured API response: see expanded «API response — structured view» "
                    "above.)\n\n"
                )
                parts.append("--- User JSON payload (sent to model) ---\n")
                parts.append(self._step5_pretty_json_or_raw(row["user_payload_json"]))
                parts.append("\n--- Raw model response text ---\n")
                parts.append(self._step5_pretty_json_or_raw(row["raw_response_text"]))
                rj = row["response_json"]
                if rj:
                    parts.append("\n--- Parsed response_json (stored) ---\n")
                    parts.append(self._step5_pretty_json_or_raw(str(rj)))
                text = "".join(parts)
        tw = self._step5_detail_text
        tw.configure(state="normal")
        tw.delete("1.0", END)
        tw.insert("1.0", text)
        tw.configure(state="disabled")

    def _on_step5_result_select(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "_step5_results_tree") or not hasattr(self, "_step5_detail_text"):
            return
        self._hide_step5_llm_response_panel()
        tv = self._step5_results_tree
        sel = tv.selection()
        if not sel:
            return
        iid = sel[0]
        vals = tv.item(iid, "values")
        if not vals:
            return
        try:
            result_id = int(vals[0])
        except (TypeError, ValueError):
            return
        try:
            conn = connect(get_db_path())
            try:
                row = fetch_step5_result_detail(conn, result_id)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            text = f"DB error: {e}"
        else:
            if row is None:
                text = "(Result not found.)"
            else:
                parts: list[str] = []
                parts.append(f"Result id: {result_id}\n")
                parts.append(
                    f"Chain: session={row['chat_session_id']} run={row['run_id']} "
                    f"manifest={row['manifest_id']} find_match={row['find_match_id']}\n"
                )
                parts.append(
                    f"Topic/Connotation ids: {row['bot1_topic_id']} / {row['bot1_connotation_id']}\n"
                )
                parts.append(
                    f"Verse: {row['surah_no']}:{row['ayah_no']}\n"
                    f"{str(row['verse_text'] or '').strip()}\n\n"
                )
                cer = row["cross_encoder_relevance"] if "cross_encoder_relevance" in row.keys() else None
                if cer is not None:
                    parts.append(f"CrossEncoder relevance (0–10): {float(cer):.3f}\n\n")
                parts.append(f"Possibility score: {row['possibility_score']}\n\n")
                parts.append("Exegesis:\n")
                parts.append(str(row["exegesis"] or "") + "\n\n")
                parts.append("Symbolic reasoning:\n")
                parts.append(str(row["symbolic_reasoning"] or "") + "\n\n")
                parts.append(
                    f"Tokens: prompt={row['prompt_tokens']} completion={row['completion_tokens']} "
                    f"total={row['total_tokens']}\n"
                )
                parts.append(f"Cost: ${float(row['cost_usd'] or 0.0):.6f}\n")
                parts.append("\n--- User JSON payload (sent to model) ---\n")
                parts.append(
                    self._step5_pretty_json_or_raw(
                        str(row["user_payload_json"]) if row["user_payload_json"] else None
                    )
                )
                parts.append("\n--- Raw model response ---\n")
                parts.append(
                    self._step5_pretty_json_or_raw(
                        str(row["raw_response_text"]) if row["raw_response_text"] else None
                    )
                )
                text = "".join(parts)
        tw = self._step5_detail_text
        tw.configure(state="normal")
        tw.delete("1.0", END)
        tw.insert("1.0", text)
        tw.configure(state="disabled")

    def _refresh_bot2_tab(self) -> None:
        if not hasattr(self, "_bot2_preview"):
            return
        self._bot2_preview.configure(state="normal")
        self._bot2_preview.delete("1.0", END)
        sid = self._current_id
        if not sid:
            self._bot2_preview.insert("1.0", "(Select or create a session.)")
            self._bot2_status.set("")
            self._bot2_preview.configure(state="disabled")
            self._bot2_copy_err_btn.configure(state="disabled")
            return
        sess = self._store.get(sid)
        title = sess.title if sess else sid[:8]
        err = self._last_bot2_error_by_session.get(sid)
        parts: list[str] = []
        parts.append("=== Bot 2 — Arabic synonyms (latest run per connotation) ===\n\n")
        try:
            conn = connect(get_db_path())
            try:
                lines = fetch_latest_bot2_display_lines(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            lines = [f"(DB error: {e})"]
        if lines:
            parts.extend(lines)
        else:
            parts.append("(No Bot 2 data yet — run Bot 1, then Run Bot 2.)\n")
        parts.append("\n=== Last Bot 2 error (this session) ===\n\n")
        if err:
            parts.append(err + "\n")
        else:
            parts.append("(None)\n")
        self._bot2_preview.insert("1.0", "".join(parts))
        self._bot2_preview.configure(state="disabled")
        if err:
            self._bot2_status.set(f"Session «{title}» — Bot 2 had errors (see below).")
            self._bot2_copy_err_btn.configure(state="normal")
        else:
            self._bot2_copy_err_btn.configure(state="disabled")
            self._bot2_status.set(f"Session «{title}» — Bot 2 synonyms for latest Bot 1 connotations.")

    def _refresh_bot_dependent_tabs(self) -> None:
        self._refresh_bot1_tab()
        self._refresh_bot2_tab()
        self._refresh_find_verses_tab()
        self._refresh_step4_tab()
        self._refresh_step5_tab()
        if hasattr(self, "_step6_pane"):
            self._step6_pane.refresh_vector_status()
        self._refresh_pipeline_summary_tab()
        self._sync_session_step_banner()

    def _refresh_pipeline_summary_tab(self) -> None:
        if not hasattr(self, "_summary_pane"):
            return
        sid = self._current_id
        by = self._pipeline_metrics.get(sid) if sid else None
        self._summary_pane.refresh_from_store(by)

    def _pipeline_step_start(self, sid: str, step: int) -> None:
        self._pipeline_step_clock[(sid, step)] = (time.monotonic(), datetime.now())

    def _pipeline_step_finish_from_partial(
        self,
        sid: str,
        step: int,
        *,
        agent: bool,
        in_tok: int,
        out_tok: int,
        in_usd: float,
        out_usd: float,
        models: str,
    ) -> None:
        key = (sid, step)
        clock = self._pipeline_step_clock.pop(key, None)
        end = datetime.now()
        if clock is not None:
            mono0, started = clock
            dur = max(0.0, time.monotonic() - mono0)
        else:
            started = end
            dur = 0.0
        m = StepPipelineMetric(
            agent_involved=agent,
            input_tokens=int(in_tok),
            output_tokens=int(out_tok),
            input_cost_usd=float(in_usd),
            output_cost_usd=float(out_usd),
            models_label=models,
            duration_secs=dur,
            started_at_iso=started.strftime("%Y-%m-%d %H:%M:%S"),
            ended_at_iso=end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._pipeline_metrics.setdefault(sid, {})[step] = m
        if self._current_id == sid:
            self._refresh_pipeline_summary_tab()

    def _schedule_session_vector_store(self, sid: str) -> None:
        sess = self._store.get(sid)
        title = sess.title if sess else None

        def _ok(_vid: str) -> None:
            if hasattr(self, "_step6_pane"):
                self._root.after(0, self._step6_pane.refresh_vector_status)

        def _err(_e: BaseException) -> None:
            if hasattr(self, "_step6_pane"):
                self._root.after(0, self._step6_pane.refresh_vector_status)

        create_session_vector_store_async(sid, title, on_success=_ok, on_error=_err)

    def _refresh_fv_scorecard_and_chart(self, sid: str | None) -> None:
        """Update Step 3 scorecard metrics and matplotlib bar chart."""
        if not hasattr(self, "_fv_chart_holder"):
            return
        if not sid:
            self._fv_score_var_bot1.set("—")
            self._fv_score_var_connotations.set("—")
            self._fv_score_var_hit_rows.set("—")
            self._fv_score_var_ayahs.set("—")
            self._fv_score_var_coverage.set("—")
            self._redraw_fv_scorecard_chart(None, error=None)
            return
        try:
            conn = connect(get_db_path())
            try:
                stats = compute_step3_find_verses_scorecard(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            self._fv_score_var_bot1.set("Error")
            self._fv_score_var_connotations.set("—")
            self._fv_score_var_hit_rows.set("—")
            self._fv_score_var_ayahs.set("—")
            self._fv_score_var_coverage.set("—")
            self._redraw_fv_scorecard_chart(None, error=str(e))
            return
        self._fv_score_var_bot1.set("Yes" if stats.has_bot1_run else "No")
        self._fv_score_var_connotations.set(str(stats.n_connotations))
        self._fv_score_var_hit_rows.set(str(stats.n_match_rows))
        self._fv_score_var_ayahs.set(str(stats.n_unique_ayahs))
        if stats.n_connotations:
            self._fv_score_var_coverage.set(
                f"{stats.n_connotations_with_any_hit} / {stats.n_connotations}"
            )
        else:
            self._fv_score_var_coverage.set("—")
        self._redraw_fv_scorecard_chart(stats, error=None)

    def _redraw_fv_scorecard_chart(
        self,
        stats: Step3FindVersesScorecard | None,
        *,
        error: str | None,
    ) -> None:
        """Rebuild matplotlib horizontal stacked bars (hits per connotation)."""
        for w in self._fv_chart_holder.winfo_children():
            w.destroy()
        self._fv_stats_mpl_canvas = None
        if error:
            ttk.Label(
                self._fv_chart_holder,
                text=f"Chart unavailable: {error}",
                foreground=MaterialColors.error,
                wraplength=720,
            ).pack(anchor="w", pady=8)
            return
        if stats is None:
            ttk.Label(
                self._fv_chart_holder,
                text="Select a session to see the scorecard chart.",
                foreground=MaterialColors.on_surface_variant,
            ).pack(anchor="w", pady=8)
            return
        if not stats.has_bot1_run:
            ttk.Label(
                self._fv_chart_holder,
                text="No Bot 1 pipeline data — run Step 1 first, then «Run Find Verses & save».",
                foreground=MaterialColors.on_surface_variant,
                wraplength=720,
                justify="left",
            ).pack(anchor="w", pady=8)
            return
        n = len(stats.bar_rows)
        if n == 0:
            ttk.Label(
                self._fv_chart_holder,
                text="Latest Bot 1 run has no connotations to chart.",
                foreground=MaterialColors.on_surface_variant,
            ).pack(anchor="w", pady=8)
            return
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except ImportError:
            ttk.Label(
                self._fv_chart_holder,
                text="Install matplotlib to show the bar chart (see requirements.txt).",
                foreground=MaterialColors.on_surface_variant,
            ).pack(anchor="w", pady=8)
            return

        h_in = max(2.8, min(14.0, 0.38 * n + 1.4))
        fig = Figure(figsize=(8.2, h_in), dpi=100, facecolor=MaterialColors.surface)
        ax = fig.subplots()
        y = list(range(n))
        w_con = [r.n_connotation_hits for r in stats.bar_rows]
        w_syn = [r.n_synonym_hits for r in stats.bar_rows]
        ax.barh(y, w_con, height=0.62, label="Connotation phrase", color="#1565c0", alpha=0.92)
        ax.barh(y, w_syn, height=0.62, left=w_con, label="Synonym phrases", color="#2e7d32", alpha=0.9)
        ax.set_yticks(y, [f"#{i + 1}" for i in y])
        ax.set_xlabel("Saved verse hits (rows)", fontsize=9)
        ax.set_title("Hits per connotation (Bot 1 order)", fontsize=11, pad=8)
        ax.legend(loc="lower right", fontsize=8, framealpha=0.95)
        xmax = max(1, max((c + s for c, s in zip(w_con, w_syn)), default=0) * 1.08 + 0.5)
        ax.set_xlim(0, xmax)
        ax.grid(axis="x", linestyle=":", alpha=0.5)
        fig.tight_layout()
        style_mpl_figure(fig)
        canvas = FigureCanvasTkAgg(fig, master=self._fv_chart_holder)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)
        self._fv_stats_mpl_canvas = canvas
        if hasattr(self, "_qr_sync_scrollregion"):
            self._root.after_idle(self._qr_sync_scrollregion)

    def _refresh_find_verses_tab(self) -> None:
        if not hasattr(self, "_find_verses_preview"):
            return
        self._find_verses_preview.configure(state="normal")
        self._find_verses_preview.delete("1.0", END)
        sid = self._current_id
        if not sid:
            self._fv_adhoc_session = None
            self._adhoc_search_hits = []
            self._adhoc_search_query = ""
            if hasattr(self, "_adhoc_save_btn"):
                self._adhoc_save_btn.configure(state="disabled")
            self._find_verses_preview.insert("1.0", "(Select or create a session.)")
            self._find_verses_status.set("")
            self._find_verses_preview.configure(state="disabled")
            self._clear_fv_pipeline_tree()
            if hasattr(self, "_fv_table_search_var"):
                self._fv_table_search_var.set("")
            if hasattr(self, "_fv_not_found_hint"):
                self._fv_not_found_hint.set("")
            self._refresh_fv_scorecard_and_chart(None)
            return

        prev = self._fv_adhoc_session
        if prev is not None and prev != sid:
            self._adhoc_search_hits = []
            self._adhoc_search_query = ""
            if hasattr(self, "_adhoc_save_btn"):
                self._adhoc_save_btn.configure(state="disabled")
        self._fv_adhoc_session = sid

        self._refresh_fv_scorecard_and_chart(sid)

        sess = self._store.get(sid)
        title = sess.title if sess else sid[:8]
        parts: list[str] = []

        parts.append("=== Quick search — preview (not in DB until Save) ===\n\n")
        qprev = (self._adhoc_search_query or "").strip()
        quick_ayah_texts: dict[tuple[int, int], str] = {}
        if qprev and self._adhoc_search_hits:
            try:
                conn = connect(get_db_path())
                try:
                    quick_ayah_texts = fetch_ayah_texts(conn, self._adhoc_search_hits)
                finally:
                    conn.close()
            except (OSError, sqlite3.Error):
                quick_ayah_texts = {}
        if qprev:
            keyword = qprev.replace(chr(10), " ")
            parts.append("Verse | Keyword | Type\n")
            parts.append("-" * 72 + "\n")
            if self._adhoc_search_hits:
                for su, ay in self._adhoc_search_hits:
                    parts.append(f"{su}:{ay} | {keyword} | quick_search_preview\n")
                    atext = quick_ayah_texts.get((int(su), int(ay)))
                    if atext:
                        parts.append(f"    {atext}\n")
            else:
                parts.append("(none — token sequence not found in corpus)\n")
            parts.append("\n")
        else:
            parts.append(
                "(Use «Search Quran» above. Results stay in memory until «Save preview to database».)\n\n"
            )

        parts.append("=== Find Verses — pipeline (find_verse_matches) ===\n\n")
        rows: list[sqlite3.Row] = []
        adhoc_rows: list[sqlite3.Row] = []
        ayah_texts: dict[tuple[int, int], str] = {}
        db_load_err: str | None = None
        try:
            conn = connect(get_db_path())
            try:
                rows = fetch_find_verse_matches_for_session(conn, sid)
                adhoc_rows = fetch_adhoc_verse_matches_for_session(conn, sid)
                refs: list[tuple[int, int]] = []
                refs.extend((int(r["surah_no"]), int(r["ayah_no"])) for r in rows)
                refs.extend((int(r["surah_no"]), int(r["ayah_no"])) for r in adhoc_rows)
                refs.extend((int(su), int(ay)) for su, ay in self._adhoc_search_hits)
                ayah_texts = fetch_ayah_texts(conn, refs)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            db_load_err = str(e)
        if db_load_err:
            parts.append(f"(DB error: {db_load_err})\n\n")
        if not rows:
            parts.append("(No rows yet — run «Run Find Verses & save» after Bot 1.)\n\n")
        else:
            parts.append(f"Total rows: {len(rows)}\n")
            parts.append("Verse | Keyword | Type\n")
            parts.append("-" * 72 + "\n")
            for r in rows:
                sk = str(r["source_kind"])
                q = str(r["query_text"]).replace("\n", " ").strip()
                su, ay = int(r["surah_no"]), int(r["ayah_no"])
                type_label = "connotation" if sk == "connotation" else "synonym"
                parts.append(f"{su}:{ay} | {q} | {type_label}\n")
                atext = ayah_texts.get((su, ay))
                if atext:
                    parts.append(f"    {atext}\n")
            parts.append("\n")

        parts.append("=== Saved quick searches (find_verse_adhoc_matches) ===\n\n")
        if db_load_err:
            parts.append("(Could not load — same DB error as above.)\n")
        elif adhoc_rows:
            grouped = group_adhoc_rows_by_query(adhoc_rows)
            parts.append("Verse | Keyword | Type\n")
            parts.append("-" * 72 + "\n")
            for qk in sorted(grouped.keys()):
                hits = grouped[qk]
                keyword = qk.replace(chr(10), " ").strip()
                for su, ay in hits:
                    parts.append(f"{su}:{ay} | {keyword} | quick_search\n")
                    atext = ayah_texts.get((int(su), int(ay)))
                    if atext:
                        parts.append(f"    {atext}\n")
            parts.append("\n")
        else:
            parts.append("(No saved quick searches for this session.)\n")

        self._find_verses_preview.insert("1.0", "".join(parts))
        self._find_verses_preview.configure(state="disabled")
        n = len(rows) if rows else 0
        na = len(adhoc_rows) if adhoc_rows else 0
        self._find_verses_status.set(
            f"Session «{title}» — pipeline: {n} row(s); saved quick search row(s): {na}."
        )
        self._refill_fv_pipeline_tree(sid, rows, ayah_texts, db_load_err)

    def _clear_fv_pipeline_tree(self) -> None:
        if not hasattr(self, "_fv_pipeline_tree"):
            return
        for iid in self._fv_pipeline_tree.get_children():
            self._fv_pipeline_tree.delete(iid)
        self._fv_pipeline_row_cache = []

    def _clear_fv_table_search(self) -> None:
        if hasattr(self, "_fv_table_search_var"):
            self._fv_table_search_var.set("")

    def _apply_fv_pipeline_table_filter(self) -> None:
        if not hasattr(self, "_fv_pipeline_tree"):
            return
        for iid in self._fv_pipeline_tree.get_children():
            self._fv_pipeline_tree.delete(iid)
        cache = self._fv_pipeline_row_cache
        q = ""
        if hasattr(self, "_fv_table_search_var"):
            q = (self._fv_table_search_var.get() or "").strip()
        verse = _parse_fv_table_surah_ayah(q) if q else None
        row_num = 1
        for vals, tag_tuple in cache:
            if q:
                if verse is not None:
                    su, ay = verse
                    want = f"{su}:{ay}"
                    vref = vals[5] if len(vals) > 5 else ""
                    if (vref or "").strip() != want:
                        continue
                else:
                    hay = " ".join(str(v) for v in vals).casefold()
                    if q.casefold() not in hay:
                        continue
            out = (str(row_num),) + vals[1:]
            self._fv_pipeline_tree.insert("", END, values=out, tags=tag_tuple)
            row_num += 1
        if hasattr(self, "_qr_sync_scrollregion"):
            self._root.after_idle(self._qr_sync_scrollregion)

    def _refill_fv_pipeline_tree(
        self,
        sid: str,
        pipeline_rows: list[sqlite3.Row],
        ayah_texts: dict[tuple[int, int], str],
        db_load_err: str | None,
    ) -> None:
        if not hasattr(self, "_fv_pipeline_tree") or not hasattr(self, "_fv_not_found_hint"):
            return
        cache: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        hit_i = 0
        row_num = 1
        if not db_load_err:
            for r in pipeline_rows:
                sk = str(r["source_kind"])
                mt = "connotation" if sk == "connotation" else "synonym"
                cid = str(int(r["bot1_connotation_id"]))
                tid_raw = r["bot2_synonym_term_id"]
                tid = "" if tid_raw is None else str(int(tid_raw))
                su, ay = int(r["surah_no"]), int(r["ayah_no"])
                verse_ref = f"{su}:{ay}"
                q = str(r["query_text"]).replace("\n", " ").strip()
                atext = (ayah_texts.get((su, ay)) or "").replace("\n", " ")
                tag = "fv_hit_odd" if hit_i % 2 else "fv_hit_even"
                cache.append(
                    (
                        (str(row_num), "Found", mt, cid, tid, verse_ref, q, atext),
                        (tag,),
                    )
                )
                hit_i += 1
                row_num += 1

        blob = self._fv_pipeline_not_found_by_session.get(sid)
        if blob is None:
            if db_load_err:
                self._fv_not_found_hint.set(f"(Could not load pipeline table: {db_load_err})")
            elif not pipeline_rows and row_num == 1:
                self._fv_not_found_hint.set(
                    "No saved pipeline matches yet — run «Run Find Verses & save» after Bot 1. "
                    "No-match diagnostics appear here after that run."
                )
            else:
                self._fv_not_found_hint.set(
                    "No-match snapshot not loaded for this session (e.g. new app session). "
                    "Run «Run Find Verses & save» again to refresh no-match rows; found hits above are from the database."
                )
        else:
            nfc, nfs = blob
            if not nfc and not nfs:
                self._fv_not_found_hint.set(
                    "Last run: every searched connotation and synonym matched at least one ayah "
                    "(empty token queries are counted separately in the completion dialog)."
                )
            else:
                self._fv_not_found_hint.set(
                    f"Last run — no verse match for {len(nfc)} connotation query/queries and "
                    f"{len(nfs)} synonym query/queries (exact token sequence in corpus)."
                )
            miss_i = 0
            for cid, txt in sorted(nfc, key=lambda t: (t[0], t[1])):
                tag = "nf_odd" if miss_i % 2 else "nf_even"
                cache.append(
                    (
                        (str(row_num), "No match", "connotation", str(cid), "", "", txt, ""),
                        (tag,),
                    )
                )
                miss_i += 1
                row_num += 1
            for cid, tid, txt in sorted(nfs, key=lambda t: (t[0], t[1], t[2])):
                tag = "nf_odd" if miss_i % 2 else "nf_even"
                cache.append(
                    (
                        (str(row_num), "No match", "synonym", str(cid), str(tid), "", txt, ""),
                        (tag,),
                    )
                )
                miss_i += 1
                row_num += 1
        self._fv_pipeline_row_cache = cache
        self._apply_fv_pipeline_table_filter()

    def _run_find_verses(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        self._begin_busy("Scanning Quran tokens…", op="find_verses")
        self._pipeline_step_start(sid, 3)

        def work() -> None:
            try:
                conn = connect(get_db_path())
                try:
                    stats = run_find_verses_for_session(conn, sid)
                finally:
                    conn.close()
            except ValueError as e:
                self._root.after(0, lambda msg=str(e): self._on_find_verses_error(msg, db=False))
            except (OSError, sqlite3.Error) as e:
                self._root.after(0, lambda msg=str(e): self._on_find_verses_error(msg, db=True))
            else:
                self._root.after(0, lambda st=stats: self._on_find_verses_success(sid, st))

        threading.Thread(target=work, daemon=True).start()

    def _on_find_verses_error(self, msg: str, *, db: bool = False) -> None:
        sid = self._current_id
        if sid:
            self._pipeline_step_clock.pop((sid, 3), None)
        if db:
            messagebox.showerror("Find Verses", msg, parent=self._root)
        else:
            messagebox.showinfo("Find Verses", msg, parent=self._root)
        self._end_busy("Ready.")

    def _on_find_verses_success(self, sid: str, stats: FindVersesStats) -> None:
        self._fv_pipeline_not_found_by_session[sid] = (
            stats.not_found_connotations,
            stats.not_found_synonyms,
        )
        self._refresh_find_verses_tab()
        self._pipeline_step_finish_from_partial(
            sid,
            3,
            agent=False,
            in_tok=0,
            out_tok=0,
            in_usd=0.0,
            out_usd=0.0,
            models=(
                f"Local scan — {stats.rows_inserted} row(s), "
                f"{stats.queries_run} query/queries"
            ),
        )
        self._refresh_step4_tab(record_summary=True)
        try:
            self._sub_notebook.select(3)
        except tk.TclError:
            pass
        body = (
            f"Saved {stats.rows_inserted} match row(s) across {stats.connotations_processed} "
            f"connotation(s). Queries run: {stats.queries_run}; "
            f"skipped empty queries: {stats.skipped_empty_queries}.\n\n"
            f"Linked {stats.match_word_rows_inserted} per-word row(s) in find_match_word_rows "
            f"(session → match → quran_tokens).\n\n"
            f"Corpus: {stats.quran_token_count} token(s) across {stats.ayah_count} ayah "
            f"from {stats.corpus_source}."
        )
        # Typical full word-by-word Quran is on the order of 10⁵ tokens; example file is 4.
        if stats.quran_token_count < 500 and stats.corpus_source != "quran.json":
            body += (
                "\n\nThis corpus is tiny (often just README’s words.example.json). "
                "Find Verses only searches what is in quran_tokens — with a few tokens, "
                "almost every real connotation will miss. Import a full Quran words JSON, then run again."
            )
        elif stats.rows_inserted == 0 and stats.quran_token_count > 0:
            body += (
                "\n\nNo ayah contained the exact contiguous token sequence for any query. "
                "The model’s Arabic must match how words are split in your imported Quran JSON "
                "(Uthmani tokens). Paraphrases, English, or different word boundaries will not match."
            )
        nc, ns = len(stats.not_found_connotations), len(stats.not_found_synonyms)
        if nc or ns:
            body += f"\n\nNo-match queries (see table below): {nc} connotation(s), {ns} synonym(s)."
        messagebox.showinfo("Find Verses", body, parent=self._root)
        self._end_busy("Ready.")

    def _run_adhoc_verse_search(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            messagebox.showinfo(
                "Quick search",
                "Select or create a session first.",
                parent=self._root,
            )
            return
        raw = self._adhoc_arabic_input.get("1.0", END)
        q = (raw or "").strip()
        if not q:
            messagebox.showinfo(
                "Quick search",
                "Enter Arabic text to search (whitespace-separated tokens).",
                parent=self._root,
            )
            return
        self._begin_busy("Searching Quran…", op="adhoc_search")

        def work() -> None:
            try:
                conn = connect(get_db_path())
                try:
                    hits, err = search_arabic_text_in_quran(conn, q)
                finally:
                    conn.close()
            except (OSError, sqlite3.Error) as e:
                self._root.after(0, lambda msg=str(e): self._on_adhoc_search_db_error(msg))
            else:
                self._root.after(
                    0,
                    lambda h=hits, er=err, qq=q: self._on_adhoc_search_done(qq, h, er),
                )

        threading.Thread(target=work, daemon=True).start()

    def _on_adhoc_search_db_error(self, msg: str) -> None:
        messagebox.showerror("Quick search", msg, parent=self._root)
        self._end_busy("Ready.")

    def _on_adhoc_search_done(
        self,
        query: str,
        hits: list[tuple[int, int]],
        err: str | None,
    ) -> None:
        if err:
            messagebox.showinfo("Quick search", err, parent=self._root)
            self._end_busy("Ready.")
            return
        self._adhoc_search_query = (query or "").strip()
        self._adhoc_search_hits = list(hits)
        if hasattr(self, "_adhoc_save_btn"):
            self._adhoc_save_btn.configure(state="normal")
        self._refresh_find_verses_tab()
        self._end_busy("Ready.")

    def _save_adhoc_verse_preview(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        q = (self._adhoc_search_query or "").strip()
        if not q:
            return
        sess = self._store.get(sid)
        title = sess.title if sess else None
        try:
            conn = connect(get_db_path())
            try:
                upsert_chat_session(conn, sid, title)
                n = save_adhoc_verse_matches(conn, sid, q, self._adhoc_search_hits)
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Quick search", str(e), parent=self._root)
            return
        self._refresh_find_verses_tab()
        messagebox.showinfo(
            "Quick search",
            f"Saved {n} row(s) for this query under the current session.",
            parent=self._root,
        )

    def _persist_question_refiner_user(self, sid: str, content: str) -> None:
        sess = self._store.get(sid)
        title = sess.title if sess else None
        try:
            conn = connect(get_db_path())
            try:
                upsert_chat_session(conn, sid, title)
                insert_question_refiner_message(
                    conn,
                    chat_session_id=sid,
                    session_title=title,
                    role="user",
                    bot_name="user",
                    content=content,
                )
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            pass

    def _persist_question_refiner_assistant(self, sid: str, result: RefineResult) -> None:
        sess = self._store.get(sid)
        title = sess.title if sess else None
        refined = extract_refined_json(result.text)
        try:
            conn = connect(get_db_path())
            try:
                upsert_chat_session(conn, sid, title)
                mid = insert_question_refiner_message(
                    conn,
                    chat_session_id=sid,
                    session_title=title,
                    role="assistant",
                    bot_name="question_refiner",
                    content=result.text,
                    model=result.model,
                    response_id=result.response_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                    commit=False,
                )
                if refined and refined.get("question") is not None:
                    q = str(refined.get("question") or "").strip()
                    if q:
                        upsert_session_refined_question(
                            conn, sid, q, mid
                        )
                conn.commit()
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            pass

    def _begin_busy(self, status_msg: str, *, op: str | None = None) -> None:
        self._busy = True
        self._busy_op = op if op is not None else "refine"
        if op in ("bot1", "bot2", "step5", "step5_shortlist", "step6"):
            self._cancel_bot_work.clear()
        self._status.set(status_msg)
        if not self._prog_fr.winfo_ismapped():
            self._prog_fr.pack(fill="x", pady=(0, 6), before=self._pipeline_banner)
        self._request_progress.start(12)
        self._send_btn.configure(state="disabled")
        self._bot1_run_btn.configure(state="disabled")
        self._bot2_run_btn.configure(state="disabled")
        if hasattr(self, "_step5_run_btn"):
            self._step5_run_btn.configure(state="disabled")
        if hasattr(self, "_step5_shortlist_btn"):
            self._step5_shortlist_btn.configure(state="disabled")
        if hasattr(self, "_step5_shortlist_rb_ce"):
            self._step5_shortlist_rb_ce.configure(state="disabled")
            self._step5_shortlist_rb_llm.configure(state="disabled")
        if hasattr(self, "_step5_shortlist_llm_provider_combo"):
            self._step5_shortlist_llm_provider_combo.configure(state="disabled")
            self._step5_shortlist_llm_model_combo.configure(state="disabled")
        if hasattr(self, "_step5_clear_btn"):
            self._step5_clear_btn.configure(state="disabled")
        if hasattr(self, "_step5_resume_btn"):
            self._step5_resume_btn.configure(state="disabled")
        if hasattr(self, "_find_verses_run_btn"):
            self._find_verses_run_btn.configure(state="disabled")
        if hasattr(self, "_adhoc_search_btn"):
            self._adhoc_search_btn.configure(state="disabled")
        if hasattr(self, "_adhoc_save_btn"):
            self._adhoc_save_btn.configure(state="disabled")
        if hasattr(self, "_step6_load_btn"):
            self._step6_load_btn.configure(state="disabled")
        if hasattr(self, "_step6_write_btn"):
            self._step6_write_btn.configure(state="disabled")
        self._sync_stop_buttons()

    def _end_busy(self, status_msg: str | None = None) -> None:
        self._busy = False
        self._busy_op = None
        self._request_progress.stop()
        if self._prog_fr.winfo_ismapped():
            self._prog_fr.pack_forget()
        if status_msg is not None:
            self._status.set(status_msg)
        self._send_btn.configure(state="normal")
        self._bot1_run_btn.configure(state="normal")
        self._bot2_run_btn.configure(state="normal")
        if hasattr(self, "_step5_run_btn"):
            self._step5_run_btn.configure(state="normal")
        if hasattr(self, "_step5_shortlist_btn"):
            self._step5_shortlist_btn.configure(state="normal")
        if hasattr(self, "_step5_shortlist_rb_ce"):
            self._step5_shortlist_rb_ce.configure(state="normal")
            self._step5_shortlist_rb_llm.configure(state="normal")
        if hasattr(self, "_step5_shortlist_llm_provider_combo"):
            self._on_step5_shortlist_method_change()
        if hasattr(self, "_step5_clear_btn"):
            self._step5_clear_btn.configure(state="normal")
        if hasattr(self, "_step5_resume_btn"):
            self._step5_resume_btn.configure(state="normal")
        if hasattr(self, "_find_verses_run_btn"):
            self._find_verses_run_btn.configure(state="normal")
        if hasattr(self, "_adhoc_search_btn"):
            self._adhoc_search_btn.configure(state="normal")
        if hasattr(self, "_adhoc_save_btn"):
            save_st = (
                "normal"
                if (self._adhoc_search_query or "").strip() and self._current_id
                else "disabled"
            )
            self._adhoc_save_btn.configure(state=save_st)
        if hasattr(self, "_step6_load_btn"):
            self._step6_load_btn.configure(state="normal")
        if hasattr(self, "_step6_write_btn"):
            self._step6_write_btn.configure(state="normal")
        self._sync_stop_buttons()

    def _sync_stop_buttons(self) -> None:
        if not hasattr(self, "_bot1_stop_btn"):
            return
        self._bot1_stop_btn.configure(
            state="normal" if self._busy_op == "bot1" else "disabled"
        )
        self._bot2_stop_btn.configure(
            state="normal" if self._busy_op == "bot2" else "disabled"
        )
        if hasattr(self, "_step5_stop_btn"):
            self._step5_stop_btn.configure(
                state="normal" if self._busy_op == "step5" else "disabled"
            )
        if hasattr(self, "_step6_stop_btn"):
            self._step6_stop_btn.configure(
                state="normal" if self._busy_op == "step6" else "disabled"
            )
        if hasattr(self, "_step5_shortlist_stop_btn"):
            self._step5_shortlist_stop_btn.configure(
                state="normal" if self._busy_op == "step5_shortlist" else "disabled"
            )

    def _request_stop_bot1(self) -> None:
        if self._busy_op == "bot1":
            self._cancel_bot_work.set()
            self._status.set("Stopping Bot 1…")

    def _request_stop_bot2(self) -> None:
        if self._busy_op == "bot2":
            self._cancel_bot_work.set()
            self._status.set("Stopping Bot 2…")

    def _request_stop_step5_shortlist(self) -> None:
        if self._busy_op == "step5_shortlist":
            self._cancel_bot_work.set()
            self._status.set("Stopping SHORTLIST…")

    def _request_stop_step5(self) -> None:
        if self._busy_op == "step5":
            self._cancel_bot_work.set()
            self._status.set("Stopping Step 5…")
            if self._step5_orchestrator is not None:
                self._step5_orchestrator.cancel()

    def _request_stop_step6(self) -> None:
        if self._busy_op == "step6":
            self._cancel_bot_work.set()
            self._status.set("Stopping Step 6…")

    def prepare_for_exit(self) -> None:
        """Cancel background work and stop Step 5 polling before destroying Tk (Ctrl+C / close)."""
        if self._step5_live_refresh_after_id is not None:
            try:
                self._root.after_cancel(self._step5_live_refresh_after_id)
            except tk.TclError:
                pass
            self._step5_live_refresh_after_id = None
        if self._bot2_refresh_after_id is not None:
            try:
                self._root.after_cancel(self._bot2_refresh_after_id)
            except tk.TclError:
                pass
            self._bot2_refresh_after_id = None
        if self._step5_poll_after_id is not None:
            try:
                self._root.after_cancel(self._step5_poll_after_id)
            except tk.TclError:
                pass
            self._step5_poll_after_id = None
        self._cancel_bot_work.set()
        orch = self._step5_orchestrator
        if orch is not None:
            orch.cancel()
            orch.join(timeout=3.0)

    def _sync_bot1_effective_model(self) -> None:
        if not hasattr(self, "_bot1_model_effective"):
            return
        self._bot1_model_effective.set(
            "Effective model: " + resolve_bot1_model(self._bot1_model_var.get())
        )

    def _on_bot1_model_var_write(self, *_args: object) -> None:
        self._sync_bot1_effective_model()

    def _on_bot1_model_focus_out(self, _event: tk.Event | None = None) -> None:
        if hasattr(self, "_bot1_model_var"):
            save_bot1_ui_model(self._bot1_model_var.get())

    def _refresh_bot1_tab(self) -> None:
        if not hasattr(self, "_bot1_preview"):
            return
        self._bot1_preview.configure(state="normal")
        self._bot1_preview.delete("1.0", END)
        sid = self._current_id
        if not sid:
            self._bot1_preview.insert("1.0", "(Select or create a session in Question refiner.)")
            self._bot1_status.set("")
            self._bot1_preview.configure(state="disabled")
            if hasattr(self, "_bot1_copy_err_btn"):
                self._bot1_copy_err_btn.configure(state="disabled")
            return
        sess = self._store.get(sid)
        refined: dict | None = None
        if sess:
            for m in reversed(sess.messages):
                if m.role == "assistant":
                    refined = extract_refined_json(m.content)
                    if refined:
                        break
        db_question: str | None = None
        try:
            conn = connect(get_db_path())
            try:
                db_question = refined_question_text_for_session(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            pass
        parts: list[str] = []
        parts.append("=== Finalized question (one per session → Bot 1 & later steps) ===\n\n")
        if refined:
            parts.append(json.dumps(refined, ensure_ascii=False, indent=2))
        elif db_question:
            parts.append(
                json.dumps({"question": db_question}, ensure_ascii=False, indent=2)
            )
            parts.append(
                "\n(from database; chat transcript may differ if you edited locally)\n"
            )
        else:
            parts.append(
                "(Not yet available — finish Question refiner with a "
                "<<<REFINED_JSON>>> … {\"question\": \"…\"} … <<<END_REFINED_JSON>>> block.)\n"
            )
        parts.append("\n\n=== Bot 1 vector stores (file_search, from OpenAI admin tab) ===\n\n")
        ui_sets = load_bot1_ui_settings()
        if ui_sets.vector_store_ids:
            parts.append(json.dumps(ui_sets.vector_store_ids, ensure_ascii=False, indent=2))
            parts.append("\n")
        else:
            parts.append("(None — optional; configure in the «OpenAI admin» tab.)\n")

        parts.append("\n=== Last Bot 1 error (this session) ===\n\n")
        err = self._last_bot1_error_by_session.get(sid)
        if err:
            parts.append(err)
            parts.append("\n")
        else:
            parts.append("(None — last run succeeded or Bot 1 not run yet.)\n")

        parts.append(
            "\n=== Last Bot 1 analysis (normalized in DB: pipeline_step_runs, "
            "bot1_topics, bot1_connotations) ===\n\n"
        )
        last: dict | None = None
        try:
            conn = connect(get_db_path())
            try:
                last = fetch_latest_bot1_analysis_dict(conn, sid)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            pass
        if last and (last.get("analysis") or last.get("question")):
            parts.append(json.dumps(last, ensure_ascii=False, indent=2))
            parts.append("\n")
        else:
            parts.append("(Not run yet for this session, or open another session.)\n")
        self._bot1_preview.insert("1.0", "".join(parts))
        self._bot1_preview.configure(state="disabled")
        title = sess.title if sess else sid[:8]
        if err:
            self._bot1_status.set(
                f"Session «{title}» — Bot 1 last run failed (see «Last Bot 1 error» below; "
                "use «Copy last Bot 1 error» if needed)."
            )
            self._bot1_copy_err_btn.configure(state="normal")
        else:
            self._bot1_copy_err_btn.configure(state="disabled")
            if refined or db_question:
                self._bot1_status.set(
                    f"Session «{title}» — finalized question recorded; you can run Bot 1."
                )
            else:
                self._bot1_status.set(
                    f"Session «{title}» — waiting for refined JSON in Question refiner."
                )

    def _totals_for_session(self, sid: str) -> dict[str, int]:
        return self._session_totals.setdefault(
            sid, {"requests": 0, "prompt": 0, "completion": 0, "total": 0}
        )

    def _add_usage(self, sid: str, r: RefineResult) -> None:
        st = self._totals_for_session(sid)
        st["requests"] += 1
        if r.prompt_tokens is not None:
            st["prompt"] += r.prompt_tokens
        if r.completion_tokens is not None:
            st["completion"] += r.completion_tokens
        if r.total_tokens is not None:
            st["total"] += r.total_tokens
        self._app_totals["requests"] += 1
        if r.prompt_tokens is not None:
            self._app_totals["prompt"] += r.prompt_tokens
        if r.completion_tokens is not None:
            self._app_totals["completion"] += r.completion_tokens
        if r.total_tokens is not None:
            self._app_totals["total"] += r.total_tokens

    def _sync_diagnostics(self, last_error: str | None = None) -> None:
        if self._sys_prompt_chars is None:
            try:
                self._sys_prompt_chars = len(load_refiner_base_instructions())
            except (OSError, RefineError):
                self._sys_prompt_chars = -1

        env_model = (os.environ.get("OPENAI_MODEL") or "").strip()
        base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip()
        has_key = bool((os.environ.get("OPENAI_API_KEY") or "").strip())

        lines: list[str] = []
        lines.append("=== Configuration ===")
        lines.append(f"OPENAI_MODEL env: {env_model or '(unset → default)'}")
        lines.append(f"Default / fallback model id: gpt-4o-mini")
        lines.append(f"OPENAI_BASE_URL: {base_url or '(default https://api.openai.com/v1)'}")
        lines.append(f"API key: {'loaded' if has_key else 'missing'}")
        lines.append(f"Temperature: {REFINE_TEMPERATURE}")
        spc = self._sys_prompt_chars
        lines.append(
            "Refiner system message: docs/chatbot-question-refiner.md "
            "or data/chat/refiner_system_base.txt"
            + (f" (~{spc} chars effective)" if spc is not None and spc >= 0 else "")
        )
        lines.append("")

        sid = self._current_id
        last = self._last_result_by_session.get(sid) if sid else None
        if last_error:
            lines.append("=== Last error ===")
            lines.append(last_error)
            lines.append("")
        elif last:
            lines.append("=== Last response (this session) ===")
            lines.append(f"Resolved model: {last.model}")
            rid = last.response_id or "—"
            if len(rid) > 36:
                rid = rid[:33] + "…"
            lines.append(f"Response id: {rid}")
            lines.append(f"Finish reason: {last.finish_reason or '—'}")
            pt = last.prompt_tokens
            ct = last.completion_tokens
            tt = last.total_tokens
            lines.append(f"Prompt tokens:     {pt if pt is not None else '—'}")
            lines.append(f"Completion tokens: {ct if ct is not None else '—'}")
            lines.append(f"Total tokens:      {tt if tt is not None else '—'}")
        else:
            lines.append("=== Last response ===")
            lines.append("(no completion in this session yet)")
        lines.append("")

        if sid:
            st = self._totals_for_session(sid)
            lines.append("=== This session totals ===")
            lines.append(f"Completions: {st['requests']}")
            lines.append(
                f"Tokens (in/out/sum): {st['prompt']} / {st['completion']} / {st['total']}"
            )
        else:
            lines.append("=== This session totals ===")
            lines.append("(no session)")
        lines.append("")

        at = self._app_totals
        lines.append("=== App totals (this run) ===")
        lines.append(f"Completions: {at['requests']}")
        lines.append(
            f"Tokens (in/out/sum): {at['prompt']} / {at['completion']} / {at['total']}"
        )

        text = "\n".join(lines)
        self._diag_text.configure(state="normal")
        self._diag_text.delete("1.0", END)
        self._diag_text.insert("1.0", text)
        self._diag_text.configure(state="disabled")

    def _append_assistant_message(self, text: str) -> None:
        prose, refined = split_assistant_for_display(text)
        self._log.insert(END, "Assistant\n", ("h_bot",))
        if prose:
            self._log.insert(END, prose + "\n")
        if refined:
            self._log.insert(END, "\n── Refined question ──\n", ("h_bot",))
            self._log.insert(END, refined + "\n", ("refined",))
        self._log.insert(END, "\n")

    def _refresh_list(self, *, select_first: bool = False) -> None:
        self._session_list.delete(0, END)
        ids = self._store.list_session_ids()
        if not ids:
            s = self._store.new_session()
            ids = [s.id]
            self._schedule_session_vector_store(s.id)
        for sid in ids:
            sess = self._store.get(sid)
            title = sess.title if sess else sid[:8]
            self._session_list.insert(END, title)
        if select_first and ids:
            self._session_list.selection_set(0)
            self._current_id = ids[0]
            self._load_session_into_log(self._current_id)
        self._sync_session_step_banner()

    def _index_to_id(self, index: int) -> str | None:
        ids = self._store.list_session_ids()
        if 0 <= index < len(ids):
            return ids[index]
        return None

    def _on_list_select(self, _event=None) -> None:
        sel = self._session_list.curselection()
        if not sel:
            return
        sid = self._index_to_id(int(sel[0]))
        if sid:
            self._current_id = sid
            self._load_session_into_log(sid)
            self._sync_diagnostics()
            self._refresh_bot_dependent_tabs()

    def _load_session_into_log(self, session_id: str) -> None:
        s = self._store.get(session_id)
        self._log.configure(state="normal")
        self._log.delete("1.0", END)
        if not s:
            self._log.configure(state="disabled")
            return
        for m in s.messages:
            if m.role == "user":
                self._log.insert(END, "You\n", ("h_user",))
                self._log.insert(END, m.content + "\n\n")
            else:
                self._append_assistant_message(m.content)
        self._log.configure(state="disabled")
        self._log.see(END)

    def _append_log(self, role: str, text: str) -> None:
        self._log.configure(state="normal")
        if role == "user":
            self._log.insert(END, "You\n", ("h_user",))
            self._log.insert(END, text + "\n\n")
        elif role == "assistant":
            self._append_assistant_message(text)
        self._log.configure(state="disabled")
        self._log.see(END)

    def _new_session(self) -> None:
        s = self._store.new_session()
        self._refresh_list(select_first=False)
        ids = self._store.list_session_ids()
        try:
            idx = ids.index(s.id)
        except ValueError:
            idx = 0
        self._session_list.selection_clear(0, END)
        self._session_list.selection_set(idx)
        self._session_list.see(idx)
        self._current_id = s.id
        self._load_session_into_log(s.id)
        self._status.set("New session.")
        self._schedule_session_vector_store(s.id)
        self._sync_diagnostics()
        self._refresh_bot_dependent_tabs()

    def _rename_session(self) -> None:
        if not self._current_id:
            return
        s = self._store.get(self._current_id)
        if not s:
            return
        new_title = simpledialog.askstring(
            "Rename session",
            "Title:",
            initialvalue=s.title,
            parent=self._root,
        )
        if new_title is None:
            return
        self._store.update_title(self._current_id, new_title)
        try:
            conn = connect(get_db_path())
            try:
                update_chat_session_title(conn, self._current_id, new_title.strip() or "Session")
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            pass
        self._refresh_list(select_first=False)
        ids = self._store.list_session_ids()
        try:
            idx = ids.index(self._current_id)
            self._session_list.selection_set(idx)
        except ValueError:
            pass

    def _delete_session(self) -> None:
        if not self._current_id:
            return
        if not messagebox.askyesno(
            "Delete session",
            _session_delete_confirmation_text(self._current_id),
            parent=self._root,
        ):
            return
        dead = self._current_id
        if dead:
            dlg: SessionDeleteProgressDialog | None = None
            err: Exception | None = None
            try:
                dlg = SessionDeleteProgressDialog(
                    self._root,
                    step_labels=SESSION_DELETE_STEP_LABELS,
                    latin_font=self._latin,
                )

                def _on_step(i: int, total: int, label: str, phase: str) -> None:
                    if dlg is not None:
                        dlg.notify_step(i, total, label, phase)

                run_session_deletion_desktop(self._store, dead, _on_step)
                if dlg is not None:
                    dlg.set_complete()
            except Exception as e:
                err = e
            finally:
                if dlg is not None:
                    try:
                        dlg.destroy()
                    except tk.TclError:
                        pass
            if err is not None:
                messagebox.showerror(
                    "Delete session",
                    f"Deletion could not finish:\n{err}",
                    parent=self._root,
                )
                return
            self._session_totals.pop(dead, None)
            self._last_result_by_session.pop(dead, None)
            self._last_bot1_error_by_session.pop(dead, None)
            self._last_bot2_error_by_session.pop(dead, None)
            self._fv_pipeline_not_found_by_session.pop(dead, None)
            self._pipeline_metrics.pop(dead, None)
            for k in list(self._pipeline_step_clock.keys()):
                if k[0] == dead:
                    self._pipeline_step_clock.pop(k, None)
        self._current_id = None
        self._refresh_list(select_first=True)
        self._sync_diagnostics()
        self._refresh_bot_dependent_tabs()

    def _send(self) -> None:
        if self._busy:
            return
        if not self._current_id:
            self._new_session()
        sid = self._current_id
        if not sid:
            return
        raw = self._input.get("1.0", END).strip()
        if not raw:
            return
        self._input.delete("1.0", END)

        self._store.append_message(sid, "user", raw)
        self._append_log("user", raw)
        self._persist_question_refiner_user(sid, raw)

        sess = self._store.get(sid)
        if not sess:
            return
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in sess.messages
            if m.role in ("user", "assistant")
        ]
        ref_instructions: str | None
        if hasattr(self, "_refiner_sys_core"):
            ref_instructions = self._refiner_sys_core.get("1.0", END).rstrip()
        else:
            ref_instructions = None

        self._begin_busy("Waiting for model…", op="refine")

        def work() -> None:
            try:
                result = refine_reply(api_messages, instructions_base=ref_instructions)
            except RefineError as e:
                err = str(e)
                self._root.after(0, lambda: self._on_refine_error(sid, err))
            except Exception as e:
                err = str(e)
                self._root.after(0, lambda: self._on_refine_error(sid, err))
            else:
                self._root.after(0, lambda r=result: self._on_refine_success(sid, r))

        threading.Thread(target=work, daemon=True).start()

    def _on_refine_error(self, sid: str, err: str) -> None:
        self._log.configure(state="normal")
        self._log.insert(END, err + "\n\n", ("err",))
        self._log.configure(state="disabled")
        self._end_busy("Error — see message above.")
        self._sync_diagnostics(last_error=err)

    def _on_refine_success(self, sid: str, result: RefineResult) -> None:
        self._last_result_by_session[sid] = result
        self._add_usage(sid, result)
        self._store.append_message(sid, "assistant", result.text)
        self._append_log("assistant", result.text)
        self._persist_question_refiner_assistant(sid, result)
        self._end_busy("Ready.")
        self._sync_diagnostics()
        self._refresh_bot_dependent_tabs()

    def _run_bot1_pipeline(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        sess = self._store.get(sid)
        if not sess:
            return
        refined: dict | None = None
        for m in reversed(sess.messages):
            if m.role == "assistant":
                refined = extract_refined_json(m.content)
                if refined:
                    break
        if not refined:
            messagebox.showinfo(
                "Bot 1",
                "No refined JSON found. Ask the assistant to finish with a "
                "<<<REFINED_JSON>>> … {\"question\": \"…\"} … <<<END_REFINED_JSON>>> block first.",
                parent=self._root,
            )
            return
        ui = load_bot1_ui_settings()
        ui.model = self._bot1_model_var.get().strip()
        save_bot1_ui_settings(ui)
        model = ui.model
        vs_ids = ui.vector_store_ids if ui.vector_store_ids else None
        core_instructions: str | None
        if hasattr(self, "_bot1_sys_core"):
            core_instructions = self._bot1_sys_core.get("1.0", END).rstrip()
        else:
            core_instructions = None

        self._begin_busy("Running Bot 1…", op="bot1")
        self._pipeline_step_start(sid, 1)

        def work() -> None:
            cancel = self._cancel_bot_work
            try:
                br = run_bot1(
                    refined,
                    model=model,
                    vector_store_ids=vs_ids,
                    temperature=ui.temperature,
                    cancel_event=cancel,
                    instructions_base=core_instructions,
                )
            except Bot1Cancelled:
                self._root.after(0, self._on_bot1_stopped)
            except Bot1Error as e:
                self._root.after(0, lambda err=e: self._on_bot1_api_error(sid, err))
            except Exception as e:
                wrapped = Bot1Error(str(e))
                self._root.after(0, lambda err=wrapped: self._on_bot1_api_error(sid, err))
            else:
                self._root.after(
                    0,
                    lambda b=br, r=refined: self._on_bot1_api_success(sid, r, b),
                )

        threading.Thread(target=work, daemon=True).start()

    def _on_bot1_stopped(self) -> None:
        sid = self._current_id
        if sid:
            self._pipeline_step_clock.pop((sid, 1), None)
        self._end_busy("Bot 1 stopped — nothing was saved.")

    def _on_bot1_api_error(self, sid: str, e: Bot1Error) -> None:
        detail = getattr(e, "detail", None)
        if detail and detail.strip() != str(e).strip():
            self._last_bot1_error_by_session[sid] = f"{e}\n\n{detail}"
        else:
            self._last_bot1_error_by_session[sid] = str(e)
        self._pipeline_step_clock.pop((sid, 1), None)
        self._refresh_bot1_tab()
        self._refresh_find_verses_tab()
        self._end_busy("Bot 1 failed — see «Last Bot 1 error» in the panel below.")

    def _on_bot1_api_success(self, sid: str, refined: dict, br: Bot1Result) -> None:
        sess = self._store.get(sid)
        session_title = sess.title if sess else None
        try:
            conn = connect(get_db_path())
            try:
                run_id = insert_bot1_step_run(
                    conn,
                    chat_session_id=sid,
                    session_title=session_title,
                    refined=refined,
                    br=br,
                )
            finally:
                conn.close()
        except (OSError, sqlite3.Error, ValueError) as e:
            messagebox.showerror(
                "Database",
                f"{e}\n\nIf tables are missing, run: python scripts/init_db.py",
                parent=self._root,
            )
            self._pipeline_step_clock.pop((sid, 1), None)
            self._end_busy("DB error.")
            return
        cin, cout, _ = split_cost_usd(
            "openai",
            (br.model or "").strip(),
            prompt_tokens=br.prompt_tokens,
            completion_tokens=br.completion_tokens,
        )
        self._pipeline_step_finish_from_partial(
            sid,
            1,
            agent=True,
            in_tok=int(br.prompt_tokens or 0),
            out_tok=int(br.completion_tokens or 0),
            in_usd=cin,
            out_usd=cout,
            models=(br.model or "").strip() or "(unknown)",
        )
        self._last_bot1_error_by_session.pop(sid, None)
        self._refresh_bot_dependent_tabs()
        try:
            self._sub_notebook.select(1)
        except tk.TclError:
            pass
        messagebox.showinfo(
            "Bot 1",
            f"Saved step «Bot 1» for this session (pipeline run id={run_id}; "
            "topics and connotations are in bot1_topics / bot1_connotations).",
            parent=self._root,
        )
        self._end_busy("Ready.")

    def _run_bot2_pipeline(self) -> None:
        if self._busy:
            return
        sid = self._current_id
        if not sid:
            return
        self._on_bot2_numeric_focus_out()
        ui = load_bot2_ui_settings()
        ui.model = self._bot2_model_var.get().strip()
        save_bot2_ui_settings(ui)

        try:
            conn = connect(get_db_path())
            try:
                rq_id = refined_question_id_for_session(conn, sid)
                rq_text = refined_question_text_for_session(conn, sid) or ""
                b1_run = latest_bot1_pipeline_run_id(conn, sid)
                raw_items = (
                    list_connotations_for_bot1_run(conn, b1_run)
                    if b1_run is not None
                    else []
                )
                items = [x for x in raw_items if x.connotation_text.strip()]
                if (
                    items
                    and
                    hasattr(self, "_bot2_skip_existing_var")
                    and self._bot2_skip_existing_var.get()
                    and b1_run is not None
                ):
                    have = bot1_connotation_ids_with_bot2_for_bot1_run(
                        conn, sid, b1_run
                    )
                    items = [x for x in items if x.bot1_connotation_id not in have]
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Database", str(e), parent=self._root)
            return

        if rq_id is None:
            messagebox.showinfo(
                "Bot 2",
                "No finalized question in the database for this session. "
                "Complete the Question refiner with <<<REFINED_JSON>>> first.",
                parent=self._root,
            )
            return
        if not items:
            skip_on = (
                hasattr(self, "_bot2_skip_existing_var")
                and self._bot2_skip_existing_var.get()
            )
            messagebox.showinfo(
                "Bot 2",
                (
                    "No Bot 1 connotations to process (all skipped as already having synonyms). "
                    "Turn off «Skip connotations that already have Bot 2 synonyms» to re-run."
                    if skip_on
                    else "No Bot 1 connotations found. Run Bot 1 for this session first."
                ),
                parent=self._root,
            )
            return

        model = ui.model
        vs_ids = ui.vector_store_ids if ui.vector_store_ids else None
        max_syn = max(1, min(30, int(ui.max_synonyms)))
        temp = ui.temperature
        core2: str | None
        if hasattr(self, "_bot2_sys_core"):
            core2 = self._bot2_sys_core.get("1.0", END).rstrip()
        else:
            core2 = None

        self._begin_busy(f"Running Bot 2… (0/{len(items)} connotations)", op="bot2")
        self._pipeline_step_start(sid, 2)

        def work() -> None:
            cancel = self._cancel_bot_work
            ok: list[tuple[ConnotationWorkItem, Bot2Result]] = []
            err_lines: list[str] = []
            n = len(items)
            stopped = False
            for i, item in enumerate(items):
                if cancel.is_set():
                    stopped = True
                    break
                self._root.after(
                    0,
                    lambda i=i, n=n: self._status.set(
                        f"Running Bot 2… ({i}/{n} connotations)"
                    ),
                )
                try:
                    br = run_bot2_synonyms(
                        connotation_text=item.connotation_text,
                        topic_text=item.topic_text,
                        refined_question=rq_text,
                        model=model,
                        vector_store_ids=vs_ids,
                        max_synonyms=max_syn,
                        temperature=temp,
                        cancel_event=cancel,
                        instructions_base=core2,
                    )
                    try:
                        c = connect(get_db_path())
                        try:
                            insert_bot2_synonym_pipeline(
                                c,
                                chat_session_id=sid,
                                refined_question_id=rq_id,
                                item=item,
                                br=br,
                            )
                        finally:
                            c.close()
                    except (OSError, sqlite3.Error, ValueError) as db_e:
                        err_lines.append(
                            f"{item.connotation_text[:48]}…\nDatabase save failed: {db_e}"
                        )
                    else:
                        ok.append((item, br))
                        self._root.after(
                            0, lambda: self._schedule_bot2_dependent_refresh()
                        )
                except Bot2Cancelled:
                    stopped = True
                    break
                except Bot2Error as e:
                    detail = getattr(e, "detail", None)
                    if detail and str(detail).strip() != str(e).strip():
                        err_lines.append(
                            f"{item.connotation_text[:48]}…\n{e}\n{detail}"
                        )
                    else:
                        err_lines.append(f"{item.connotation_text[:48]}…\n{e}")
                except Exception as e:
                    err_lines.append(f"{item.connotation_text[:48]}…\n{e}")
            self._root.after(
                0,
                lambda: self._apply_bot2_batch(
                    sid, rq_id, ok, err_lines, stopped=stopped
                ),
            )

        threading.Thread(target=work, daemon=True).start()

    def _apply_bot2_batch(
        self,
        sid: str,
        rq_id: int,
        ok: list[tuple[ConnotationWorkItem, Bot2Result]],
        err_lines: list[str],
        *,
        stopped: bool = False,
    ) -> None:
        saved = len(ok)
        if self._bot2_refresh_after_id is not None:
            try:
                self._root.after_cancel(self._bot2_refresh_after_id)
            except tk.TclError:
                pass
            self._bot2_refresh_after_id = None
        if saved <= 0:
            self._pipeline_step_clock.pop((sid, 2), None)
        else:
            pt = ct = 0
            cin = cout = 0.0
            models_order: list[str] = []
            for _, br in ok:
                pti = int(br.prompt_tokens or 0)
                cti = int(br.completion_tokens or 0)
                pt += pti
                ct += cti
                a, b, _ = split_cost_usd(
                    "openai",
                    (br.model or "").strip(),
                    prompt_tokens=pti,
                    completion_tokens=cti,
                )
                cin += a
                cout += b
                m = (br.model or "").strip()
                if m and m not in models_order:
                    models_order.append(m)
            self._pipeline_step_finish_from_partial(
                sid,
                2,
                agent=True,
                in_tok=pt,
                out_tok=ct,
                in_usd=cin,
                out_usd=cout,
                models=", ".join(models_order) if models_order else "(unknown)",
            )
        if err_lines:
            self._last_bot2_error_by_session[sid] = "\n\n---\n\n".join(err_lines)
        else:
            self._last_bot2_error_by_session.pop(sid, None)
        self._refresh_bot_dependent_tabs()
        try:
            self._sub_notebook.select(2)
        except tk.TclError:
            pass
        msg = f"Bot 2 saved synonyms for {saved} connotation(s)."
        if stopped:
            msg = (
                f"Bot 2 stopped. Saved {saved} connotation(s) completed before stop."
                + (f" {len(err_lines)} call(s) had also failed." if err_lines else "")
            )
        elif err_lines:
            msg += f" {len(err_lines)} call(s) failed — see «Last Bot 2 error» in the panel."
        messagebox.showinfo("Bot 2", msg, parent=self._root)
        self._end_busy("Ready." if not stopped else "Bot 2 stopped.")

    def _copy_bot2_error_to_clipboard(self) -> None:
        sid = self._current_id
        if not sid:
            return
        text = self._last_bot2_error_by_session.get(sid)
        if not text:
            return
        self._root.clipboard_clear()
        self._root.clipboard_append(text)
        self._status.set("Copied last Bot 2 error to clipboard.")

    def _copy_bot1_error_to_clipboard(self) -> None:
        sid = self._current_id
        if not sid:
            return
        text = self._last_bot1_error_by_session.get(sid)
        if not text:
            return
        self._root.clipboard_clear()
        self._root.clipboard_append(text)
        self._status.set("Copied last Bot 1 error to clipboard.")
