"""Lanes Lexicon tab: roots and entries from lexicon_roots / lexicon_entries with accordion rows."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import END, VERTICAL, ttk
from typing import Callable

from src.db.connection import connect
from src.db.lane_lexicon import LaneLexiconEntryRow, LaneLexiconRootGroup, fetch_lane_lexicon_groups
from src.ui.lexicon_display import entry_dialog_title, heading_display_label


def _truncate_cell(val: str, max_len: int = 220) -> str:
    if not val:
        return ""
    if len(val) > max_len:
        return val[: max_len - 3] + "..."
    return val


class LanesLexiconTab:
    def __init__(
        self,
        parent: ttk.Frame,
        root: tk.Tk,
        db_path: Callable[[], Path],
        *,
        latin_font: str,
        arabic_font: str,
        on_definition: Callable[[str, str], None],
    ) -> None:
        self._tk = root
        self._db_path = db_path
        self._on_definition = on_definition
        self._latin = latin_font
        self._arabic = arabic_font
        self._raw_groups: list[LaneLexiconRootGroup] = []
        self._word_count_sort_reverse = False
        self._search_after_id: str | None = None
        self._entry_map: dict[str, tuple[str, str]] = {}
        self._row_counter = 0
        self._iid_seq = 0

        bar = ttk.Frame(parent, padding=(6, 6, 6, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Search:").pack(side="left")
        self._search_var = tk.StringVar(master=root)
        ent = ttk.Entry(bar, textvariable=self._search_var, width=36)
        ent.pack(side="left", padx=(6, 12))
        self._search_var.trace_add("write", self._schedule_search_rebuild)
        ent.bind("<Return>", lambda _e: self._rebuild_tree())

        ref_kw: dict = {"text": "Reload from database", "command": self.refresh_from_disk}
        ttk.Button(bar, **ref_kw).pack(side="left", padx=(0, 12))

        self._status_var = tk.StringVar(master=root, value="Open this tab or click Reload to load lexicon data.")
        ttk.Label(bar, textvariable=self._status_var).pack(side="left", padx=(8, 0))

        grid_frame = ttk.Frame(parent, padding=(6, 0, 6, 8))
        grid_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("sr", "root_word", "entry", "description", "word_count")
        self._tree = ttk.Treeview(
            grid_frame,
            columns=cols,
            show="tree headings",
            selectmode="browse",
            style="Verse.Treeview",
        )
        self._tree.heading("#0", text="Root / entry")
        self._tree.column("#0", width=200, stretch=True, minwidth=120)
        self._tree.heading("sr", text="Sr. #")
        self._tree.heading("root_word", text="Root word")
        self._tree.heading("entry", text="Entry")
        self._tree.heading("description", text="Description")
        self._tree.heading(
            "word_count",
            text="Description word count ▲",
            command=self._toggle_word_count_sort,
        )
        self._tree.column("sr", width=52, stretch=False)
        self._tree.column("root_word", width=110, stretch=True)
        self._tree.column("entry", width=200, stretch=True)
        self._tree.column("description", width=360, stretch=True)
        self._tree.column("word_count", width=140, stretch=False)

        vsb = ttk.Scrollbar(grid_frame, orient=VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(grid_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        grid_frame.rowconfigure(0, weight=1)
        grid_frame.columnconfigure(0, weight=1)

        self._tree.bind("<Double-1>", self._on_double_click)

    def _schedule_search_rebuild(self, *_args: object) -> None:
        if self._search_after_id is not None:
            self._tk.after_cancel(self._search_after_id)
        self._search_after_id = self._tk.after(280, self._debounced_rebuild)

    def _debounced_rebuild(self) -> None:
        self._search_after_id = None
        self._rebuild_tree()

    def _toggle_word_count_sort(self) -> None:
        self._word_count_sort_reverse = not self._word_count_sort_reverse
        arrow = "▼" if self._word_count_sort_reverse else "▲"
        self._tree.heading("word_count", text=f"Description word count {arrow}")
        self._rebuild_tree()

    def refresh_from_disk(self) -> None:
        path = self._db_path()
        if not path.is_file():
            self._raw_groups = []
            self._status_var.set("Database file not found.")
            self._clear_tree()
            return
        try:
            conn = connect(path)
        except OSError as e:
            self._status_var.set(str(e))
            self._raw_groups = []
            self._clear_tree()
            return
        try:
            self._raw_groups = fetch_lane_lexicon_groups(conn)
        finally:
            conn.close()
        n_roots = len(self._raw_groups)
        n_entries = sum(len(g.entries) for g in self._raw_groups)
        self._status_var.set(
            f"Loaded {n_roots} root(s), {n_entries} entr{'y' if n_entries == 1 else 'ies'} from database."
        )
        self._rebuild_tree()

    def _clear_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._entry_map.clear()

    def _matches_search(self, group: LaneLexiconRootGroup, q: str) -> bool:
        if not q:
            return True
        if q in group.root_word.lower():
            return True
        for e in group.entries:
            if q in e.heading_raw.lower():
                return True
            if q in e.definition.lower():
                return True
        return False

    def _sorted_entries(self, entries: tuple[LaneLexiconEntryRow, ...]) -> list[LaneLexiconEntryRow]:
        return sorted(
            entries,
            key=lambda e: (e.word_count, e.seq),
            reverse=self._word_count_sort_reverse,
        )

    def _sorted_groups(self, groups: list[LaneLexiconRootGroup]) -> list[LaneLexiconRootGroup]:
        def sort_key(g: LaneLexiconRootGroup) -> tuple[int, int, str]:
            max_wc = max((e.word_count for e in g.entries), default=0)
            min_wc = min((e.word_count for e in g.entries), default=0)
            primary = max_wc if self._word_count_sort_reverse else min_wc
            tie = -min_wc if self._word_count_sort_reverse else max_wc
            return (primary, tie, g.root_word.lower())

        return sorted(groups, key=sort_key, reverse=self._word_count_sort_reverse)

    def _rebuild_tree(self) -> None:
        self._clear_tree()
        q = self._search_var.get().strip().lower()
        filtered = [g for g in self._raw_groups if self._matches_search(g, q)]
        ordered = self._sorted_groups(filtered)
        self._row_counter = 0
        min_group = 2
        for group in ordered:
            entries = self._sorted_entries(group.entries)
            if len(entries) >= min_group:
                pid = self._next_iid()
                n = len(entries)
                self._tree.insert(
                    "",
                    END,
                    iid=pid,
                    text=group.root_word,
                    values=("", group.root_word, f"({n} entries)", "", ""),
                    open=False,
                )
                for e in entries:
                    self._row_counter += 1
                    sr = str(self._row_counter)
                    htext = heading_display_label(e.heading_raw) or f"Entry {e.seq}"
                    title = entry_dialog_title(e.seq, e.heading_raw)
                    prev = _truncate_cell(e.definition, 240)
                    cid = self._next_iid()
                    self._tree.insert(
                        pid,
                        END,
                        iid=cid,
                        text=htext,
                        values=(
                            sr,
                            "",
                            htext,
                            prev,
                            str(e.word_count),
                        ),
                    )
                    self._entry_map[cid] = (title, e.definition)
            else:
                e = entries[0]
                self._row_counter += 1
                sr = str(self._row_counter)
                htext = heading_display_label(e.heading_raw) or f"Entry {e.seq}"
                title = entry_dialog_title(e.seq, e.heading_raw)
                prev = _truncate_cell(e.definition, 240)
                oid = self._next_iid()
                self._tree.insert(
                    "",
                    END,
                    iid=oid,
                    text=htext,
                    values=(
                        sr,
                        group.root_word,
                        htext,
                        prev,
                        str(e.word_count),
                    ),
                )
                self._entry_map[oid] = (title, e.definition)

        if q and not ordered:
            self._status_var.set("No rows match the search filter.")
        elif self._raw_groups:
            self._status_var.set(
                f"Showing {len(ordered)} root group(s) "
                f"({sum(len(g.entries) for g in ordered)} entries)"
                + (f' — filter: "{self._search_var.get().strip()}"' if q else "")
                + "."
            )

    def _next_iid(self) -> str:
        self._iid_seq += 1
        return f"ll{self._iid_seq}"

    def _on_double_click(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        iid = self._tree.identify_row(event.y)  # type: ignore[attr-defined]
        if not iid:
            return
        ch = self._tree.get_children(iid)
        if ch:
            cur = bool(self._tree.item(iid, "open"))
            self._tree.item(iid, open=not cur)
            return
        pair = self._entry_map.get(iid)
        if pair:
            self._on_definition(pair[0], pair[1])
