"""
Desktop SQLite explorer (Tkinter).

Run from project root:
    python server.py
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import BOTH, END, VERTICAL, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ui.app_fonts import ensure_ui_fonts_ready  # noqa: E402
from src.ui.app_icons import AppIconSet  # noqa: E402
from src.ui.material_theme import MaterialColors, apply_material_theme  # noqa: E402

_ARABIC_UI_FAMILY, _LATIN_UI_FAMILY = ensure_ui_fonts_ready(ROOT)

from src.chat.openai_health import OpenAiHealthResult, check_openai_api_health  # noqa: E402
from src.config import get_db_path  # noqa: E402
from src.db.connection import connect  # noqa: E402
from src.db.introspection import (  # noqa: E402
    fetch_table_rows,
    get_columns_with_keys,
    list_user_tables,
    table_row_count,
)
from src.db.verse_hierarchy import (  # noqa: E402
    VerseWordNode,
    fetch_verse_word_hierarchy,
    list_surahs_with_tokens,
    max_ayah_in_surah,
)
from src.ui.lexicon_display import (  # noqa: E402
    entry_dialog_title,
    heading_display_label,
)

try:
    from src.ui.verse_hierarchy_chart import VerseHierarchyChart  # noqa: E402
except ImportError:
    VerseHierarchyChart = None  # type: ignore[misc, assignment]

def _truncate_cell(val: object, max_len: int = 200) -> str:
    if val is None:
        return ""
    s = str(val)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _kalimat_cell(w: VerseWordNode) -> str:
    if not w.kalimat:
        return ""
    return " · ".join(k.surface for k in w.kalimat)


class DbExplorerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Quran Lexicon — Database Explorer")
        self.root.geometry("1280x820")
        self.root.minsize(960, 600)
        self._icons = AppIconSet(self.root)
        apply_material_theme(
            self.root, latin_family=_LATIN_UI_FAMILY, arabic_family=_ARABIC_UI_FAMILY
        )

        self.db_path = get_db_path()
        self._current_table: str | None = None

        top = ttk.Frame(self.root, padding=(14, 12, 14, 8))
        top.pack(fill="x")
        hdr = ttk.Frame(top)
        hdr.pack(side="left", fill="x", expand=True)
        db_img = self._icons.get("storage")
        title_row = ttk.Frame(hdr)
        title_row.pack(anchor="w")
        if db_img:
            ttk.Label(title_row, image=db_img).pack(side="left", padx=(0, 8))
        ttk.Label(
            title_row,
            text="Quran Lexicon",
            font=(_LATIN_UI_FAMILY, 14, "bold"),
            foreground=MaterialColors.primary,
        ).pack(side="left")
        path_lbl = ttk.Label(
            hdr,
            text=str(self.db_path),
            font=(_LATIN_UI_FAMILY, 9),
            foreground=MaterialColors.on_surface_variant,
        )
        path_lbl.pack(anchor="w", pady=(4, 0))
        ref_img = self._icons.get("refresh")
        refresh_kw: dict = {"text": "Refresh tables", "command": self._reload_navigation}
        if ref_img:
            refresh_kw["image"] = ref_img
            refresh_kw["compound"] = "left"

        right_bar = ttk.Frame(top)
        right_bar.pack(side="right")
        ttk.Button(right_bar, **refresh_kw).pack(side="right")
        self._openai_check_btn = ttk.Button(
            right_bar,
            text="Check API",
            command=self._on_openai_health_check,
        )
        self._openai_check_btn.pack(side="right", padx=(0, 8))
        self._openai_health_var = tk.StringVar(value="OpenAI: checking…")
        self._last_openai_health_detail: str | None = None
        self._openai_health_lbl = tk.Label(
            right_bar,
            textvariable=self._openai_health_var,
            font=(_LATIN_UI_FAMILY, 9),
            bg=MaterialColors.surface,
            fg=MaterialColors.on_surface_variant,
        )
        self._openai_health_lbl.pack(side="right", padx=(0, 8))
        self._openai_health_lbl.bind(
            "<Double-Button-1>", self._on_openai_health_detail_dclick
        )

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))

        tab_db = ttk.Frame(notebook)
        tab_verse = ttk.Frame(notebook)
        tab_chat = ttk.Frame(notebook)
        tab_openai = ttk.Frame(notebook)
        tab_lanes = ttk.Frame(notebook)
        notebook.add(tab_verse, text="Verse roots")
        notebook.add(tab_chat, text="Pipeline")
        notebook.add(tab_openai, text="OpenAI admin")
        notebook.add(tab_lanes, text="Lanes Lexicon")
        notebook.add(tab_db, text="Database")

        paned = ttk.PanedWindow(tab_db, orient="horizontal")
        paned.pack(fill=BOTH, expand=True)

        left = ttk.Frame(paned, width=320)
        paned.add(left, weight=0)

        self.nav_tree = ttk.Treeview(
            left, selectmode="browse", show="tree", style="Browse.Treeview"
        )
        nav_scroll = ttk.Scrollbar(left, orient=VERTICAL, command=self.nav_tree.yview)
        self.nav_tree.configure(yscrollcommand=nav_scroll.set)
        self.nav_tree.pack(side="left", fill=BOTH, expand=True)
        nav_scroll.pack(side="right", fill="y")

        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        ctrl = ttk.Frame(right)
        ctrl.pack(fill="x", pady=(0, 4))
        ttk.Label(ctrl, text="Rows (limit):").pack(side="left")
        self.limit_var = tk.StringVar(value="200")
        self.limit_spin = ttk.Spinbox(
            ctrl, from_=10, to=5000, width=8, textvariable=self.limit_var
        )
        self.limit_spin.pack(side="left", padx=(4, 12))
        load_img = self._icons.get("table")
        load_kw: dict = {
            "text": "Load table",
            "command": self._load_selected_table,
        }
        if load_img:
            load_kw["image"] = load_img
            load_kw["compound"] = "left"
        ttk.Button(ctrl, **load_kw).pack(side="left", padx=(0, 4))
        self.status_var = tk.StringVar(value="Select a table in the tree.")
        ttk.Label(ctrl, textvariable=self.status_var).pack(side="right")

        grid_frame = ttk.Frame(right)
        grid_frame.pack(fill=BOTH, expand=True)

        self.data_tree = ttk.Treeview(
            grid_frame, show="headings", style="Browse.Treeview"
        )
        vsb = ttk.Scrollbar(grid_frame, orient=VERTICAL, command=self.data_tree.yview)
        hsb = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.data_tree.xview)
        self.data_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.data_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        grid_frame.rowconfigure(0, weight=1)
        grid_frame.columnconfigure(0, weight=1)

        self.nav_tree.bind("<<TreeviewSelect>>", self._on_nav_select)
        self.nav_tree.bind("<Double-1>", lambda _e: self._load_selected_table())

        self._build_verse_roots_tab(tab_verse)

        from src.ui.question_refiner_tab import QuestionRefinerTab  # noqa: E402

        self._question_refiner = QuestionRefinerTab(
            tab_chat,
            self.root,
            arabic_font=_ARABIC_UI_FAMILY,
            latin_font=_LATIN_UI_FAMILY,
            icon_set=self._icons,
            on_lexicon_definition=self._show_lexicon_entry_description,
        )

        from src.ui.openai_admin_tab import OpenAIAdminTab  # noqa: E402

        self._openai_admin = OpenAIAdminTab(
            tab_openai,
            self.root,
            latin_font=_LATIN_UI_FAMILY,
            icon_set=self._icons,
        )

        from src.ui.lanes_lexicon_tab import LanesLexiconTab  # noqa: E402

        self._lanes_lexicon = LanesLexiconTab(
            tab_lanes,
            self.root,
            lambda: self.db_path,
            latin_font=_LATIN_UI_FAMILY,
            arabic_font=_ARABIC_UI_FAMILY,
            on_definition=self._show_lexicon_entry_description,
        )

        if not self.db_path.is_file():
            messagebox.showwarning(
                "Database missing",
                f"No database file at:\n{self.db_path}\n\nRun: python database.py",
            )
            self._reload_verse_surah_list()
        else:
            self._reload_navigation()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.root.after(200, self._schedule_startup_openai_health)

    def _schedule_startup_openai_health(self) -> None:
        self._run_openai_health_async(from_user=False)

    def _on_openai_health_check(self) -> None:
        self._run_openai_health_async(from_user=True)

    def _on_openai_health_detail_dclick(self, _event: tk.Event | None = None) -> None:
        if self._last_openai_health_detail:
            messagebox.showinfo("OpenAI API", self._last_openai_health_detail)

    def _run_openai_health_async(self, *, from_user: bool) -> None:
        def work() -> None:
            try:
                result = check_openai_api_health()
            except Exception as e:
                result = OpenAiHealthResult(
                    ok=False, summary="Check failed", detail=str(e)
                )
            self.root.after(0, lambda: self._apply_openai_health_result(result))

        if from_user:
            self._openai_health_var.set("OpenAI: checking…")
            self._openai_health_lbl.configure(fg=MaterialColors.on_surface_variant)
            self._last_openai_health_detail = None
        try:
            self._openai_check_btn.configure(state="disabled")
        except tk.TclError:
            pass

        threading.Thread(target=work, daemon=True).start()

    def _apply_openai_health_result(self, r: OpenAiHealthResult) -> None:
        try:
            self._openai_check_btn.configure(state="normal")
        except tk.TclError:
            pass
        if r.ok:
            self._openai_health_var.set("OpenAI: OK")
            self._openai_health_lbl.configure(fg=MaterialColors.success)
            self._last_openai_health_detail = (
                "The API key can access the OpenAI API (models list succeeded)."
            )
        else:
            self._openai_health_var.set(f"OpenAI: {r.summary}")
            self._openai_health_lbl.configure(fg=MaterialColors.error)
            self._last_openai_health_detail = r.detail or r.summary

    def _on_close(self) -> None:
        try:
            self._question_refiner.prepare_for_exit()
        except (tk.TclError, RuntimeError, AttributeError):
            pass
        self.root.destroy()

    def _build_verse_roots_tab(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, padding=(4, 4, 4, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text="Surah:").pack(side="left")
        self.verse_surah_var = tk.StringVar(value="1")
        self.verse_surah_combo = ttk.Combobox(
            bar, textvariable=self.verse_surah_var, width=8, state="readonly"
        )
        self.verse_surah_combo.pack(side="left", padx=(4, 12))
        self.verse_surah_combo.bind("<<ComboboxSelected>>", self._on_verse_surah_changed)

        ttk.Label(bar, text="Ayah:").pack(side="left")
        self.verse_ayah_var = tk.StringVar(value="1")
        self.verse_ayah_spin = ttk.Spinbox(
            bar, from_=1, to=286, width=6, textvariable=self.verse_ayah_var
        )
        self.verse_ayah_spin.pack(side="left", padx=(4, 12))
        lv_img = self._icons.get("menu_book")
        lv_kw: dict = {"text": "Load verse", "command": self._load_verse_hierarchy}
        if lv_img:
            lv_kw["image"] = lv_img
            lv_kw["compound"] = "left"
        ttk.Button(bar, **lv_kw).pack(side="left")
        self.verse_status_var = tk.StringVar(
            value="Select surah and ayah, then Load verse."
        )
        ttk.Label(bar, textvariable=self.verse_status_var).pack(side="left", padx=(16, 0))

        verse_nb = ttk.Notebook(parent)
        verse_nb.pack(fill=BOTH, expand=True, padx=4, pady=(0, 4))

        graph_tab = ttk.Frame(verse_nb)
        table_tab = ttk.Frame(verse_nb)
        hierarchy_tab = ttk.Frame(verse_nb)
        verse_nb.add(graph_tab, text="Graph (interactive)")
        verse_nb.add(table_tab, text="Table")
        verse_nb.add(hierarchy_tab, text="Hierarchical list")

        self.verse_chart = None
        if VerseHierarchyChart is not None:
            try:
                self.verse_chart = VerseHierarchyChart(
                    graph_tab,
                    on_pick=self._on_verse_graph_pick,
                )
            except Exception:
                self.verse_chart = None
                ttk.Label(
                    graph_tab,
                    text="Could not start graph view. Install: pip install matplotlib networkx",
                    padding=16,
                ).pack(expand=True)
        else:
            ttk.Label(
                graph_tab,
                text="Graph view requires matplotlib and networkx.\n\npip install matplotlib networkx",
                padding=16,
                justify="center",
            ).pack(expand=True)

        if self.verse_chart is None:

            class _StubChart:
                def clear(self) -> None:
                    pass

                def render(self, *_a, **_k) -> None:
                    pass

            self.verse_chart = _StubChart()

        table_frame = ttk.Frame(table_tab, padding=(6, 4, 6, 8))
        table_frame.pack(fill=BOTH, expand=True)
        cols = (
            "word_no",
            "token",
            "kalimat",
            "root_id",
            "root",
            "seq",
            "heading",
            "definition",
        )
        self.verse_table = ttk.Treeview(
            table_frame,
            columns=cols,
            show="tree headings",
            selectmode="browse",
            style="Verse.Treeview",
        )
        self.verse_table.heading("#0", text="Word / entry")
        self.verse_table.column("#0", width=240, stretch=True, minwidth=160)
        self.verse_table.heading("word_no", text="Word #")
        self.verse_table.heading("token", text="Token (Uthmani)")
        self.verse_table.heading("kalimat", text="Kalimāt (morph.)")
        self.verse_table.heading("root_id", text="Root ID")
        self.verse_table.heading("root", text="Root")
        self.verse_table.heading("seq", text="Seq")
        self.verse_table.heading("heading", text="Heading")
        self.verse_table.heading("definition", text="Definition (preview)")
        self.verse_table.column("word_no", width=64, stretch=False)
        self.verse_table.column("token", width=120, stretch=True)
        self.verse_table.column("kalimat", width=160, stretch=True)
        self.verse_table.column("root_id", width=72, stretch=False)
        self.verse_table.column("root", width=100, stretch=True)
        self.verse_table.column("seq", width=48, stretch=False)
        self.verse_table.column("heading", width=200, stretch=True)
        self.verse_table.column("definition", width=360, stretch=True)
        tv_s = ttk.Scrollbar(
            table_frame, orient=VERTICAL, command=self.verse_table.yview
        )
        th_s = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.verse_table.xview
        )
        self.verse_table.configure(
            yscrollcommand=tv_s.set, xscrollcommand=th_s.set
        )
        self.verse_table.grid(row=0, column=0, sticky="nsew")
        tv_s.grid(row=0, column=1, sticky="ns")
        th_s.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self._verse_table_entry_map: dict[str, tuple[str, str]] = {}
        self.verse_table.bind("<Double-1>", self._on_verse_table_double_click)

        tree_frame = ttk.Frame(hierarchy_tab, padding=(6, 4, 6, 8))
        tree_frame.pack(fill=BOTH, expand=True)
        self.verse_tree = ttk.Treeview(
            tree_frame, show="tree", style="Verse.Treeview"
        )
        vvs = ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.verse_tree.yview)
        self.verse_tree.configure(yscrollcommand=vvs.set)
        self.verse_tree.pack(side="left", fill=BOTH, expand=True)
        vvs.pack(side="right", fill="y")
        self._verse_tree_entry_map: dict[str, tuple[str, str]] = {}
        self.verse_tree.bind("<Double-1>", self._on_verse_tree_double_click)

    def _on_verse_graph_pick(
        self,
        _node_id: str,
        full_label: str,
        definition: str | None = None,
        entry_heading: str | None = None,
    ) -> None:
        self.verse_status_var.set(full_label)
        if definition is not None:
            self._show_lexicon_entry_description(
                entry_heading or "Lexicon entry",
                definition,
            )

    def _show_lexicon_entry_description(self, title: str, definition: str) -> None:
        from src.ui.arabic_display import shape_arabic_display

        win = tk.Toplevel(self.root)
        win.title("Definition")
        win.geometry("820x580")
        win.minsize(480, 320)
        win.configure(bg=MaterialColors.surface)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill=BOTH, expand=True)
        ttk.Label(
            frm,
            text=title,
            wraplength=780,
            font=(_ARABIC_UI_FAMILY, 13, "bold"),
            foreground=MaterialColors.primary,
        ).pack(anchor="w", pady=(0, 10))
        body = definition.strip() if definition else ""
        if not body:
            body = "(No definition text stored for this entry.)"
        display_body = shape_arabic_display(body)
        st = ScrolledText(
            frm,
            wrap="word",
            height=26,
            font=(_ARABIC_UI_FAMILY, 12),
            bg=MaterialColors.surface_container,
            fg=MaterialColors.on_surface,
            insertbackground=MaterialColors.primary,
            relief="flat",
            padx=12,
            pady=12,
            highlightthickness=1,
            highlightbackground=MaterialColors.outline,
        )
        st.insert("1.0", display_body)
        st.config(state="disabled")
        st.pack(fill=BOTH, expand=True)
        ttk.Button(frm, text="Close", command=win.destroy).pack(pady=(10, 0))

    def _reload_verse_surah_list(self) -> None:
        if not self.db_path.is_file():
            self.verse_surah_combo["values"] = ()
            self.verse_status_var.set("Database file not found.")
            return
        try:
            conn = connect(self.db_path)
        except OSError as e:
            self.verse_status_var.set(str(e))
            return
        try:
            surahs = list_surahs_with_tokens(conn)
        finally:
            conn.close()
        self.verse_surah_combo["values"] = tuple(str(s) for s in surahs)
        if surahs:
            cur = self.verse_surah_var.get()
            if cur not in {str(s) for s in surahs}:
                self.verse_surah_var.set(str(surahs[0]))
            self._sync_verse_ayah_bounds()
            self.verse_status_var.set(
                f"{len(surahs)} surah(s) with token data — choose verse and Load."
            )
        else:
            self.verse_status_var.set(
                "No rows in quran_tokens — import Quran data (python database.py)."
            )

    def _sync_verse_ayah_bounds(self) -> None:
        if not self.db_path.is_file():
            return
        try:
            s = int(self.verse_surah_var.get())
        except ValueError:
            return
        try:
            conn = connect(self.db_path)
        except OSError:
            return
        try:
            m = max_ayah_in_surah(conn, s)
        finally:
            conn.close()
        self.verse_ayah_spin.config(from_=1, to=max(1, m))
        try:
            a = int(self.verse_ayah_var.get())
        except ValueError:
            a = 1
        if m >= 1 and a > m:
            self.verse_ayah_var.set(str(m))
        elif m == 0:
            self.verse_ayah_var.set("1")

    def _on_verse_surah_changed(self, _event=None) -> None:
        self._sync_verse_ayah_bounds()

    def _load_verse_hierarchy(self) -> None:
        if not self.db_path.is_file():
            messagebox.showwarning("Database missing", "Run: python database.py")
            return
        try:
            surah = int(self.verse_surah_var.get())
            ayah = int(self.verse_ayah_var.get())
        except ValueError:
            messagebox.showinfo("Invalid input", "Surah and ayah must be numbers.")
            return
        try:
            conn = connect(self.db_path)
        except OSError as e:
            messagebox.showerror("Error", str(e))
            return
        try:
            nodes = fetch_verse_word_hierarchy(conn, surah, ayah)
        except Exception as e:
            messagebox.showerror("Query failed", str(e))
            return
        finally:
            conn.close()

        self.verse_tree.delete(*self.verse_tree.get_children())
        self.verse_table.delete(*self.verse_table.get_children())
        self._verse_table_entry_map.clear()
        self._verse_tree_entry_map.clear()
        self.verse_chart.clear()
        if not nodes:
            self.verse_status_var.set(
                f"No tokens for surah {surah}, ayah {ayah} (import data or pick another verse)."
            )
            return

        self.verse_chart.render(surah, ayah, nodes)
        self._populate_verse_table(nodes)

        verse_id = self.verse_tree.insert(
            "",
            END,
            text=f"Surah {surah} · Ayah {ayah} ({len(nodes)} word(s))",
            open=True,
        )
        for w in nodes:
            wl = f"Word {w.word_no}: {w.token_uthmani}"
            w_id = self.verse_tree.insert(
                verse_id,
                END,
                text=wl,
                open=True,
            )
            for seg in w.kalimat:
                seg_lbl = seg.surface
                if seg.pos:
                    seg_lbl = f"{seg.surface}  [{seg.pos}]"
                self.verse_tree.insert(w_id, END, text=seg_lbl, open=False)
            if w.root_id is not None and w.root_word:
                r_id = self.verse_tree.insert(
                    w_id,
                    END,
                    text=f"Root: {w.root_word}",
                    open=True,
                )
                for h in w.entry_headings:
                    clean = heading_display_label(h.label)
                    disp = clean if clean.strip() else f"Entry {h.seq}"
                    hid = self.verse_tree.insert(
                        r_id,
                        END,
                        text=disp,
                        open=False,
                    )
                    title = entry_dialog_title(h.seq, h.label)
                    body = (h.definition or "").strip()
                    if body:
                        preview = _truncate_cell(body, 280)
                    else:
                        preview = "(no definition text stored)"
                    did = self.verse_tree.insert(hid, END, text=preview)
                    self._verse_tree_entry_map[hid] = (title, h.definition or "")
                    self._verse_tree_entry_map[did] = (title, h.definition or "")
                if not w.entry_headings:
                    self.verse_tree.insert(
                        r_id,
                        END,
                        text="(no lexicon headings for this root)",
                    )
            elif w.root_id is not None:
                self.verse_tree.insert(
                    w_id,
                    END,
                    text=f"Root id {w.root_id} (missing lexicon_roots row)",
                )
            else:
                self.verse_tree.insert(w_id, END, text="(no mapped root)")
        self.verse_status_var.set(
            f"Surah {surah}, ayah {ayah}: {len(nodes)} word(s)."
        )

    def _populate_verse_table(self, nodes: list[VerseWordNode]) -> None:
        """Table with accordion-style parents when a word has multiple lexicon headings."""
        min_group = 2
        row_i = 0
        for w in nodes:
            wn = str(w.word_no)
            tok = w.token_uthmani
            kali = _kalimat_cell(w)
            tree_label = f"Word {w.word_no}: {w.token_uthmani}"
            if w.root_id is not None and w.root_word:
                rid = str(w.root_id)
                rw = w.root_word
                heads = w.entry_headings
                if not heads:
                    iid = f"vt{row_i}"
                    row_i += 1
                    self.verse_table.insert(
                        "",
                        END,
                        iid=iid,
                        text=tree_label,
                        values=(
                            wn,
                            tok,
                            kali,
                            rid,
                            rw,
                            "",
                            "(no headings)",
                            "",
                        ),
                    )
                    continue
                if len(heads) >= min_group:
                    iid_p = f"vt{row_i}"
                    row_i += 1
                    n = len(heads)
                    self.verse_table.insert(
                        "",
                        END,
                        iid=iid_p,
                        text=tree_label,
                        values=(
                            wn,
                            tok,
                            kali,
                            rid,
                            rw,
                            "",
                            f"({n} entries)",
                            "Expand row for headings and definitions",
                        ),
                        open=False,
                    )
                    for h in heads:
                        title = entry_dialog_title(h.seq, h.label)
                        htext = heading_display_label(h.label) or f"Entry {h.seq}"
                        prev = _truncate_cell(h.definition, 140)
                        iid = f"vt{row_i}"
                        row_i += 1
                        self.verse_table.insert(
                            iid_p,
                            END,
                            iid=iid,
                            text=htext,
                            values=(
                                "",
                                "",
                                "",
                                "",
                                "",
                                str(h.seq),
                                htext,
                                prev,
                            ),
                        )
                        self._verse_table_entry_map[iid] = (title, h.definition)
                else:
                    h = heads[0]
                    title = entry_dialog_title(h.seq, h.label)
                    htext = heading_display_label(h.label) or f"Entry {h.seq}"
                    prev = _truncate_cell(h.definition, 140)
                    iid = f"vt{row_i}"
                    row_i += 1
                    self.verse_table.insert(
                        "",
                        END,
                        iid=iid,
                        text=tree_label,
                        values=(
                            wn,
                            tok,
                            kali,
                            rid,
                            rw,
                            str(h.seq),
                            htext,
                            prev,
                        ),
                    )
                    self._verse_table_entry_map[iid] = (title, h.definition)
            elif w.root_id is not None:
                iid = f"vt{row_i}"
                row_i += 1
                self.verse_table.insert(
                    "",
                    END,
                    iid=iid,
                    text=tree_label,
                    values=(
                        wn,
                        tok,
                        kali,
                        str(w.root_id),
                        "",
                        "",
                        f"(missing lexicon_roots id {w.root_id})",
                        "",
                    ),
                )
            else:
                iid = f"vt{row_i}"
                row_i += 1
                self.verse_table.insert(
                    "",
                    END,
                    iid=iid,
                    text=tree_label,
                    values=(
                        wn,
                        tok,
                        kali,
                        "",
                        "",
                        "",
                        "(no mapped root)",
                        "",
                    ),
                )

    def _on_verse_table_double_click(self, event=None) -> None:
        if event is not None:
            iid = self.verse_table.identify_row(event.y)
        else:
            sel = self.verse_table.selection()
            iid = sel[0] if sel else ""
        if not iid:
            return
        ch = self.verse_table.get_children(iid)
        if ch:
            cur = bool(self.verse_table.item(iid, "open"))
            self.verse_table.item(iid, open=not cur)
            return
        pair = self._verse_table_entry_map.get(iid)
        if not pair:
            return
        title, definition = pair
        self._show_lexicon_entry_description(title, definition)

    def _on_verse_tree_double_click(self, event=None) -> None:
        if event is not None:
            iid = self.verse_tree.identify_row(event.y)
        else:
            sel = self.verse_tree.selection()
            iid = sel[0] if sel else ""
        if not iid:
            return
        pair = self._verse_tree_entry_map.get(iid)
        if pair:
            self._show_lexicon_entry_description(pair[0], pair[1])
            return
        ch = self.verse_tree.get_children(iid)
        if ch:
            cur = bool(self.verse_tree.item(iid, "open"))
            self.verse_tree.item(iid, open=not cur)

    def _reload_navigation(self) -> None:
        for item in self.nav_tree.get_children():
            self.nav_tree.delete(item)
        self.nav_tree.insert("", "end", "root", text="Tables", open=True)
        if not self.db_path.is_file():
            self.status_var.set("Database file not found.")
            self._reload_verse_surah_list()
            self._lanes_lexicon.refresh_from_disk()
            return
        try:
            conn = connect(self.db_path)
        except OSError as e:
            messagebox.showerror("Error", str(e))
            self._reload_verse_surah_list()
            self._lanes_lexicon.refresh_from_disk()
            return
        try:
            tables = list_user_tables(conn)
            for tname in tables:
                tid = f"table:{tname}"
                self.nav_tree.insert("root", "end", tid, text=tname, open=False)
                try:
                    cols = get_columns_with_keys(conn, tname)
                except Exception:
                    cols = []
                for c in cols:
                    parts: list[str] = []
                    if c.pk:
                        parts.append("PK")
                    if c.is_fk:
                        parts.append("FK")
                    prefix = f"[{'+'.join(parts)}] " if parts else ""
                    ref = f" → {c.fk_refs}" if c.fk_refs else ""
                    label = f"{prefix}{c.name}{ref}"
                    cid = f"col:{tname}:{c.name}"
                    self.nav_tree.insert(tid, "end", cid, text=label)
        finally:
            conn.close()
        self.status_var.set(f"{len(tables)} tables — expand to see columns.")
        self._reload_verse_surah_list()
        self._lanes_lexicon.refresh_from_disk()

    def _on_nav_select(self, _event=None) -> None:
        sel = self.nav_tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid.startswith("table:"):
            self._current_table = iid.split(":", 1)[1]
            self.status_var.set(
                f"Table: {self._current_table} — click Load table or double-click the table."
            )
        elif iid.startswith("col:"):
            parts = iid.split(":", 2)
            self._current_table = parts[1]
            self.status_var.set(f"Column of table: {self._current_table}")
        else:
            self._current_table = None

    def _load_selected_table(self) -> None:
        if not self.db_path.is_file():
            messagebox.showwarning("Database missing", "Run: python database.py")
            return
        sel = self.nav_tree.selection()
        table: str | None = self._current_table
        if sel:
            iid = sel[0]
            if iid.startswith("col:"):
                parts = iid.split(":", 2)
                table = parts[1]
            elif iid.startswith("table:"):
                table = iid.split(":", 1)[1]
        if not table:
            messagebox.showinfo("Select a table", "Select a table (or column) in the tree.")
            return
        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 200
        try:
            conn = connect(self.db_path)
        except OSError as e:
            messagebox.showerror("Error", str(e))
            return
        try:
            total = table_row_count(conn, table)
            cols, rows = fetch_table_rows(conn, table, limit=limit, offset=0)
        except Exception as e:
            messagebox.showerror("Query failed", str(e))
            return
        finally:
            conn.close()

        self.data_tree.delete(*self.data_tree.get_children())
        self.data_tree["columns"] = cols
        for c in cols:
            self.data_tree.heading(c, text=c)
            self.data_tree.column(c, width=120, stretch=True)
        for i, row in enumerate(rows):
            vals = tuple(_truncate_cell(v) for v in row)
            self.data_tree.insert("", END, iid=f"r{i}", values=vals)
        shown = len(rows)
        self.status_var.set(f"{table}: showing {shown} of {total} row(s) (limit {limit}).")


def main() -> None:
    app = DbExplorerApp()
    try:
        app.root.mainloop()
    except KeyboardInterrupt:
        try:
            app._question_refiner.prepare_for_exit()
        except (tk.TclError, RuntimeError, AttributeError):
            pass
        try:
            app.root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    main()
