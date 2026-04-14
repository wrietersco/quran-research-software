"""OpenAI admin: vector stores, files, and Bot 1 file_search attachment."""

from __future__ import annotations

import os
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, filedialog, messagebox, simpledialog, ttk

from src.chat.bot1_ui_settings import load_bot1_ui_settings, save_bot1_ui_settings
from src.chat.bot2_ui_settings import load_bot2_ui_settings, save_bot2_ui_settings
from src.chat.step6_ui_settings import load_step6_ui_settings
from src.db.chat_pipeline import map_openai_vector_store_id_to_chat_sessions
from src.db.connection import connect
from src.openai_platform.resources import (
    OpenAIAdminError,
    attach_file_to_vector_store,
    create_vector_store,
    delete_file,
    delete_vector_store,
    delete_vector_store_file,
    list_files,
    list_vector_store_files,
    list_vector_stores,
    upload_file_to_openai,
)
from src.ui.app_icons import AppIconSet
from src.ui.material_theme import MaterialColors, style_tk_listbox


class OpenAIAdminTab:
    def __init__(
        self,
        parent: ttk.Frame,
        root: tk.Tk,
        *,
        latin_font: str,
        icon_set: AppIconSet | None = None,
    ) -> None:
        self._root = root
        self._latin = latin_font
        self._icons = icon_set or AppIconSet(root)
        self._vs_ids: list[str] = []
        self._file_ids: list[str] = []
        self._vs_file_ids: list[str] = []
        self._vs_file_names: list[str | None] = []
        self._bot1_ids: list[str] = []
        self._bot2_ids: list[str] = []

        outer = ttk.Frame(parent, padding=(6, 6, 6, 8))
        outer.pack(fill=BOTH, expand=True)

        intro_row = ttk.Frame(outer)
        intro_row.pack(anchor="w", fill="x", pady=(0, 8))
        cl = self._icons.get("cloud")
        if cl:
            ttk.Label(intro_row, image=cl).pack(side="left", padx=(0, 8))
        ttk.Label(
            intro_row,
            wraplength=900,
            justify="left",
            font=(latin_font, 10),
            text=(
                "This tab lists every vector store on your OpenAI account (including unrelated projects). "
                "Step 6 / PARI gets its own per-session store (names usually start with quran-session-). "
                "Bot 1 and Bot 2 never get auto-created stores: the two lower lists are only for optionally "
                "attaching file_search to some stores you pick; leave them empty and those bots do not use "
                "vector stores. The left list marks stores this app does not reference in its database or settings."
            ),
        ).pack(side="left", fill="x", expand=True)

        err_fr = ttk.LabelFrame(outer, text="Last API message", padding=6)
        err_fr.pack(fill="x", pady=(0, 8))
        self._err_text = tk.Text(
            err_fr,
            height=4,
            wrap="word",
            state="disabled",
            relief="flat",
            font=("Consolas", 9),
            bg=MaterialColors.surface_container_high,
            fg=MaterialColors.on_surface,
            highlightthickness=1,
            highlightbackground=MaterialColors.outline,
        )
        self._err_text.pack(fill="x")
        hb = ttk.Frame(err_fr)
        hb.pack(fill="x", pady=(4, 0))
        ttk.Button(hb, text="Copy message", command=self._copy_err).pack(side=tk.LEFT)

        pan = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pan.pack(fill=BOTH, expand=True)

        left = ttk.Frame(pan, width=420)
        pan.add(left, weight=1)

        lf_vs = ttk.LabelFrame(left, text="Vector stores", padding=6)
        lf_vs.pack(fill=BOTH, expand=True, pady=(0, 8))
        self._vs_list = tk.Listbox(
            lf_vs,
            height=10,
            font=("Consolas", 9),
            selectmode=tk.SINGLE,
            exportselection=False,
        )
        style_tk_listbox(self._vs_list, latin_family="Consolas", size=9)
        sb_vs = ttk.Scrollbar(lf_vs, orient=VERTICAL, command=self._vs_list.yview)
        self._vs_list.configure(yscrollcommand=sb_vs.set)
        self._vs_list.pack(side=LEFT, fill=BOTH, expand=True)
        sb_vs.pack(side=RIGHT, fill="y")
        self._vs_list.bind("<<ListboxSelect>>", lambda _e: self._on_vs_select())

        r_i = self._icons.get("refresh")
        u_i = self._icons.get("folder")
        t_i = self._icons.get("tune")

        bf_vs = ttk.Frame(lf_vs)
        bf_vs.pack(fill="x", pady=(6, 0))
        kw_vs0: dict = {"text": "Refresh", "command": self._refresh_vector_stores}
        if r_i:
            kw_vs0["image"] = r_i
            kw_vs0["compound"] = "left"
        ttk.Button(bf_vs, **kw_vs0).pack(side=LEFT, padx=(0, 6))
        ttk.Button(bf_vs, text="Create…", command=self._create_vector_store).pack(
            side=LEFT, padx=(0, 6)
        )
        ttk.Button(bf_vs, text="Delete", command=self._delete_vector_store).pack(side=LEFT)

        lf_files = ttk.LabelFrame(left, text="Files (platform)", padding=6)
        lf_files.pack(fill=BOTH, expand=True)
        self._file_list = tk.Listbox(
            lf_files,
            height=10,
            font=("Consolas", 9),
            selectmode=tk.SINGLE,
        )
        style_tk_listbox(self._file_list, latin_family="Consolas", size=9)
        sb_f = ttk.Scrollbar(lf_files, orient=VERTICAL, command=self._file_list.yview)
        self._file_list.configure(yscrollcommand=sb_f.set)
        self._file_list.pack(side=LEFT, fill=BOTH, expand=True)
        sb_f.pack(side=RIGHT, fill="y")

        bf_f = ttk.Frame(lf_files)
        bf_f.pack(fill="x", pady=(6, 0))
        kw_f0: dict = {"text": "Refresh", "command": self._refresh_files}
        if r_i:
            kw_f0["image"] = r_i
            kw_f0["compound"] = "left"
        ttk.Button(bf_f, **kw_f0).pack(side=LEFT, padx=(0, 6))
        kw_up: dict = {"text": "Upload…", "command": self._upload_file}
        if u_i:
            kw_up["image"] = u_i
            kw_up["compound"] = "left"
        ttk.Button(bf_f, **kw_up).pack(side=LEFT, padx=(0, 6))
        ttk.Button(bf_f, text="Delete", command=self._delete_platform_file).pack(side=LEFT)

        right = ttk.Frame(pan, width=480)
        pan.add(right, weight=1)

        lf_vsf = ttk.LabelFrame(right, text="Files in selected vector store", padding=6)
        lf_vsf.pack(fill=BOTH, expand=True, pady=(0, 8))
        self._vsf_list = tk.Listbox(
            lf_vsf,
            height=8,
            font=("Consolas", 9),
            selectmode=tk.SINGLE,
        )
        style_tk_listbox(self._vsf_list, latin_family="Consolas", size=9)
        sb_vsf = ttk.Scrollbar(lf_vsf, orient=VERTICAL, command=self._vsf_list.yview)
        self._vsf_list.configure(yscrollcommand=sb_vsf.set)
        self._vsf_list.pack(side=LEFT, fill=BOTH, expand=True)
        sb_vsf.pack(side=RIGHT, fill="y")

        bf_vsf = ttk.Frame(lf_vsf)
        bf_vsf.pack(fill="x", pady=(6, 0))
        kw_vsf0: dict = {"text": "Refresh", "command": self._refresh_vs_files}
        if r_i:
            kw_vsf0["image"] = r_i
            kw_vsf0["compound"] = "left"
        ttk.Button(bf_vsf, **kw_vsf0).pack(side=LEFT, padx=(0, 6))
        ttk.Button(bf_vsf, text="Attach selected platform file", command=self._attach_file).pack(
            side=LEFT, padx=(0, 6)
        )
        ttk.Button(bf_vsf, text="Remove from store", command=self._detach_vs_file).pack(side=LEFT)

        lf_bot1 = ttk.LabelFrame(
            right, text="Attach vector stores to Bot 1 (optional file_search)", padding=6
        )
        lf_bot1.pack(fill=BOTH, expand=True)
        ttk.Label(
            lf_bot1,
            font=(latin_font, 9),
            wraplength=440,
            text=(
                "If you leave nothing highlighted, Bot 1 runs without searching any vector store. "
                "If you do want RAG-style lookup, the list below is the same full catalog as on the left: "
                "multi-select the stores to search, then Save. That list is global (all sessions), "
                "separate from Step 6’s per-session store. Saved in data/chat/bot1_ui_settings.json."
            ),
        ).pack(anchor="w", pady=(0, 4))
        self._bot1_list = tk.Listbox(
            lf_bot1,
            height=6,
            font=("Consolas", 9),
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        style_tk_listbox(self._bot1_list, latin_family="Consolas", size=9)
        sb_b = ttk.Scrollbar(lf_bot1, orient=VERTICAL, command=self._bot1_list.yview)
        self._bot1_list.configure(yscrollcommand=sb_b.set)
        self._bot1_list.pack(side=LEFT, fill=BOTH, expand=True)
        sb_b.pack(side=RIGHT, fill="y")

        bf_b = ttk.Frame(lf_bot1)
        bf_b.pack(fill="x", pady=(6, 0))
        skw: dict = {"text": "Save selection for Bot 1", "command": self._save_bot1_selection}
        if t_i:
            skw["image"] = t_i
            skw["compound"] = "left"
        ttk.Button(bf_b, **skw).pack(side=LEFT)

        lf_bot2 = ttk.LabelFrame(
            right, text="Attach vector stores to Bot 2 (optional file_search)", padding=6
        )
        lf_bot2.pack(fill=BOTH, expand=True)
        ttk.Label(
            lf_bot2,
            font=(latin_font, 9),
            wraplength=440,
            text=(
                "Same idea as Bot 1: empty selection means Bot 2 does not use file_search. "
                "The list is the full account catalog for convenience; choose any subset for the synonyms step, "
                "then Save. Global for all sessions; not the Step 6 session store. "
                "Saved in data/chat/bot2_ui_settings.json."
            ),
        ).pack(anchor="w", pady=(0, 4))
        self._bot2_list = tk.Listbox(
            lf_bot2,
            height=6,
            font=("Consolas", 9),
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        style_tk_listbox(self._bot2_list, latin_family="Consolas", size=9)
        sb_b2 = ttk.Scrollbar(lf_bot2, orient=VERTICAL, command=self._bot2_list.yview)
        self._bot2_list.configure(yscrollcommand=sb_b2.set)
        self._bot2_list.pack(side=LEFT, fill=BOTH, expand=True)
        sb_b2.pack(side=RIGHT, fill="y")

        bf_b2 = ttk.Frame(lf_bot2)
        bf_b2.pack(fill="x", pady=(6, 0))
        skw2: dict = {"text": "Save selection for Bot 2", "command": self._save_bot2_selection}
        if t_i:
            skw2["image"] = t_i
            skw2["compound"] = "left"
        ttk.Button(bf_b2, **skw2).pack(side=LEFT)

        key_ok = bool((os.environ.get("OPENAI_API_KEY") or "").strip())
        if key_ok:
            self._set_err("(Ready — use Refresh to load vector stores and files.)")
        else:
            self._set_err("OPENAI_API_KEY is not set. Add it to .env and restart.")

    def _set_err(self, msg: str) -> None:
        self._err_text.configure(state="normal")
        self._err_text.delete("1.0", END)
        self._err_text.insert("1.0", msg)
        self._err_text.configure(state="disabled")

    def _copy_err(self) -> None:
        self._root.clipboard_clear()
        self._root.clipboard_append(self._err_text.get("1.0", END).strip())

    def _local_vector_store_refs(self) -> tuple[set[str], dict[str, list[str]]]:
        """OpenAI vector store ids referenced by this app, plus human-readable usage lines."""
        refs: set[str] = set()
        lines: dict[str, list[str]] = {}

        def tag(vsid: str, line: str) -> None:
            vsid = str(vsid or "").strip()
            if not vsid:
                return
            refs.add(vsid)
            lines.setdefault(vsid, []).append(line)

        try:
            conn = connect()
            try:
                by_vs = map_openai_vector_store_id_to_chat_sessions(conn)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            by_vs = {}
        for vsid, pairs in by_vs.items():
            for _sid, title in pairs:
                t = self._clip_title_for_list(title)
                tag(vsid, f'Step 6 / PARI — session "{t}"')
        for vsid in load_bot1_ui_settings().vector_store_ids:
            tag(str(vsid), "Bot 1 file_search (shared, all sessions)")
        for vsid in load_bot2_ui_settings().vector_store_ids:
            tag(str(vsid), "Bot 2 file_search (shared, all sessions)")
        for vsid in load_step6_ui_settings().extra_vector_store_ids:
            tag(str(vsid), "Step 6 PARI extra file_search (shared)")
        return refs, lines

    @staticmethod
    def _clip_title_for_list(title: str, max_len: int = 40) -> str:
        t = (title or "").strip()
        if len(t) <= max_len:
            return t
        return t[: max_len - 1] + "…"

    def _format_vector_store_list_label(
        self,
        vs_id: str,
        name: str | None,
        *,
        refs: set[str],
        lines: dict[str, list[str]],
    ) -> str:
        vs_id = str(vs_id or "").strip()
        nm = (name or "").strip() or "(no name)"
        core = f"{nm}  [{vs_id}]"
        if vs_id in refs:
            extra = lines.get(vs_id, [])
            if extra:
                joined = "; ".join(extra)
                if len(core) + len(joined) > 240:
                    joined = joined[: 210] + "…"
                return f"{core}  |  {joined}"
            return core
        low = nm.lower()
        if low.startswith("quran-session-"):
            return f"[orphan app-style name, not in local DB]  {core}"
        return f"[not tracked by this app]  {core}"

    def _refresh_vector_stores(self) -> None:
        refs, usage_lines = self._local_vector_store_refs()
        try:
            rows = list_vector_stores()
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        self._vs_list.delete(0, END)
        self._vs_ids = []
        for r in rows:
            sid = r["id"]
            self._vs_ids.append(sid)
            name = r.get("name") or ""
            self._vs_list.insert(
                END,
                self._format_vector_store_list_label(
                    sid, name, refs=refs, lines=usage_lines
                ),
            )
        self._sync_bot1_list(rows, refs=refs, lines=usage_lines)
        self._sync_bot2_list(rows, refs=refs, lines=usage_lines)
        self._set_err(f"Loaded {len(rows)} vector store(s).")
        self._refresh_vs_files()

    def _sync_bot1_list(
        self,
        rows: list[dict],
        *,
        refs: set[str],
        lines: dict[str, list[str]],
    ) -> None:
        self._bot1_list.delete(0, END)
        self._bot1_ids = []
        saved = set(load_bot1_ui_settings().vector_store_ids)
        sel_idx: list[int] = []
        for i, r in enumerate(rows):
            sid = r["id"]
            self._bot1_ids.append(sid)
            name = r.get("name") or ""
            self._bot1_list.insert(
                END,
                self._format_vector_store_list_label(
                    sid, name, refs=refs, lines=lines
                ),
            )
            if sid in saved:
                sel_idx.append(i)
        for j in sel_idx:
            self._bot1_list.selection_set(j)

    def _sync_bot2_list(
        self,
        rows: list[dict],
        *,
        refs: set[str],
        lines: dict[str, list[str]],
    ) -> None:
        self._bot2_list.delete(0, END)
        self._bot2_ids = []
        saved = set(load_bot2_ui_settings().vector_store_ids)
        sel_idx: list[int] = []
        for i, r in enumerate(rows):
            sid = r["id"]
            self._bot2_ids.append(sid)
            name = r.get("name") or ""
            self._bot2_list.insert(
                END,
                self._format_vector_store_list_label(
                    sid, name, refs=refs, lines=lines
                ),
            )
            if sid in saved:
                sel_idx.append(i)
        for j in sel_idx:
            self._bot2_list.selection_set(j)

    def _on_vs_select(self) -> None:
        self._refresh_vs_files()

    def _selected_vs_id(self) -> str | None:
        sel = self._vs_list.curselection()
        if not sel:
            return None
        i = int(sel[0])
        if 0 <= i < len(self._vs_ids):
            return self._vs_ids[i]
        return None

    def _refresh_vs_files(self) -> None:
        vs = self._selected_vs_id()
        self._vsf_list.delete(0, END)
        self._vs_file_ids = []
        self._vs_file_names = []
        if not vs:
            return
        try:
            rows = list_vector_store_files(vs)
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        for r in rows:
            fid = r.get("id") or ""
            self._vs_file_ids.append(fid)
            fn = (r.get("filename") or "").strip()
            self._vs_file_names.append(fn or None)
            st = r.get("status") or ""
            if fn:
                self._vsf_list.insert(END, f"{fn}  [{fid}]  ({st})")
            else:
                self._vsf_list.insert(END, f"(no filename)  [{fid}]  ({st})")
        self._set_err(f"Vector store {vs}: {len(rows)} file(s).")

    def _refresh_files(self) -> None:
        try:
            rows = list_files()
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        self._file_list.delete(0, END)
        self._file_ids = []
        for r in rows:
            fid = r["id"]
            self._file_ids.append(fid)
            fn = r.get("filename") or ""
            self._file_list.insert(END, f"{fn}  [{fid}]")
        self._set_err(f"Loaded {len(rows)} file(s).")

    def _create_vector_store(self) -> None:
        name = simpledialog.askstring(
            "New vector store",
            "Name:",
            parent=self._root,
        )
        if name is None:
            return
        try:
            create_vector_store(name=name)
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        self._refresh_vector_stores()

    def _prompt_vector_store_delete_mode(
        self, *, vs_id: str, vs_name: str, n_files: int
    ) -> str | None:
        """
        Return ``'store_only'``, ``'store_and_files'``, or ``None`` if cancelled.
        """
        result: list[str | None] = [None]
        dlg = tk.Toplevel(self._root)
        dlg.title("Delete vector store")
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.resizable(True, False)
        pad = {"padx": 12, "pady": 6}
        nm = vs_name.strip() or "(no name)"
        ttk.Label(
            dlg,
            text=f"Vector store name:\n{nm}\n\nID:\n{vs_id}",
            wraplength=520,
            justify="left",
        ).pack(anchor="w", **pad)
        choice = tk.IntVar(value=0)
        rb0 = ttk.Radiobutton(
            dlg,
            text=(
                "Delete the vector store only. "
                "OpenAI File objects that were attached stay in your account "
                "(you can delete them separately under Files (platform))."
            ),
            variable=choice,
            value=0,
        )
        rb0.pack(anchor="w", padx=12, pady=(8, 4))
        rb1_text = (
            f"Also delete each OpenAI File object listed in this store, one by one "
            f"({n_files} file(s); cannot be undone), then remove the vector store."
            if n_files
            else "Also delete OpenAI File objects in this store (no files attached — same as above)."
        )
        rb1 = ttk.Radiobutton(
            dlg,
            text=rb1_text,
            variable=choice,
            value=1,
        )
        rb1.pack(anchor="w", padx=12, pady=(4, 8))
        if n_files == 0:
            rb1.state(["disabled"])

        def on_ok() -> None:
            if n_files == 0:
                result[0] = "store_only"
            else:
                result[0] = "store_and_files" if int(choice.get()) == 1 else "store_only"
            dlg.destroy()

        def on_cancel() -> None:
            result[0] = None
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(bf, text="Continue", command=on_ok).pack(side=LEFT, padx=(0, 8))
        ttk.Button(bf, text="Cancel", command=on_cancel).pack(side=LEFT)
        dlg.protocol("WM_DELETE_WINDOW", on_cancel)
        dlg.update_idletasks()
        w = max(dlg.winfo_reqwidth(), 540)
        dlg.geometry(f"{int(w)}x{dlg.winfo_reqheight()}")
        self._root.wait_window(dlg)
        return result[0]

    def _delete_vector_store_files_with_progress(
        self, vs_id: str, file_rows: list[dict]
    ) -> list[str]:
        """
        Detach each file from the vector store, delete the File object on OpenAI,
        then delete the vector store. Runs on the UI thread with a progress window.
        Returns a list of human-readable error lines (empty on full success).
        """
        errors: list[str] = []
        n = len(file_rows)
        top = tk.Toplevel(self._root)
        top.title("Deleting vector store files")
        top.transient(self._root)
        top.grab_set()
        fr = ttk.Frame(top, padding=12)
        fr.pack(fill=BOTH, expand=True)
        status = tk.StringVar(value="Preparing…")
        ttk.Label(fr, textvariable=status, wraplength=520, justify="left").pack(
            anchor="w", pady=(0, 8)
        )
        pb = ttk.Progressbar(
            fr, mode="determinate", maximum=max(1, n), length=480
        )
        pb.pack(fill="x", pady=(0, 8))
        top.update_idletasks()
        top.geometry(f"{max(560, top.winfo_reqwidth())}x{top.winfo_reqheight() + 8}")

        for i, row in enumerate(file_rows):
            fid = str(row.get("id") or "").strip()
            if not fid:
                continue
            fn = (row.get("filename") or "").strip() or fid
            status.set(f"File {i + 1} of {n}: {fn}")
            pb["value"] = float(i)
            top.update_idletasks()
            top.update()
            try:
                delete_vector_store_file(vs_id, fid)
            except OpenAIAdminError as e:
                errors.append(f"Detach {fid} from vector store: {e}")
            try:
                delete_file(fid)
            except OpenAIAdminError as e:
                errors.append(f"Delete OpenAI file {fid}: {e}")
            pb["value"] = float(i + 1)
            top.update_idletasks()
            top.update()

        status.set("Removing vector store…")
        pb["value"] = float(max(1, n))
        top.update_idletasks()
        top.update()
        try:
            delete_vector_store(vs_id)
        except OpenAIAdminError as e:
            errors.append(f"Delete vector store {vs_id}: {e}")
        top.grab_release()
        top.destroy()
        return errors

    def _delete_vector_store(self) -> None:
        vs = self._selected_vs_id()
        if not vs:
            messagebox.showinfo("Vector store", "Select a vector store first.", parent=self._root)
            return
        vs_name = ""
        try:
            for r in list_vector_stores():
                if r["id"] == vs:
                    vs_name = (r.get("name") or "").strip()
                    break
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        try:
            file_rows = list_vector_store_files(vs)
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        mode = self._prompt_vector_store_delete_mode(
            vs_id=vs, vs_name=vs_name, n_files=len(file_rows)
        )
        if mode is None:
            return
        if mode == "store_only":
            try:
                delete_vector_store(vs)
            except OpenAIAdminError as e:
                self._set_err(str(e))
                return
            self._refresh_vector_stores()
            self._refresh_vs_files()
            self._set_err(f"Deleted vector store {vs} (files were not removed from OpenAI).")
            return
        if not file_rows:
            try:
                delete_vector_store(vs)
            except OpenAIAdminError as e:
                self._set_err(str(e))
                return
            self._refresh_vector_stores()
            self._refresh_vs_files()
            self._refresh_files()
            self._set_err(f"Deleted vector store {vs} (no files were attached).")
            return
        err_lines = self._delete_vector_store_files_with_progress(vs, file_rows)
        self._refresh_vector_stores()
        self._refresh_files()
        self._refresh_vs_files()
        msg = (
            f"Deleted vector store {vs} and removed {len(file_rows)} file object(s) from OpenAI."
        )
        if err_lines:
            msg += "\n\nSome steps reported errors:\n" + "\n".join(err_lines[:20])
            if len(err_lines) > 20:
                msg += f"\n… and {len(err_lines) - 20} more."
        self._set_err(msg)

    def _upload_file(self) -> None:
        path = filedialog.askopenfilename(parent=self._root, title="Upload file to OpenAI")
        if not path:
            return
        try:
            upload_file_to_openai(Path(path))
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        self._refresh_files()
        self._set_err(f"Uploaded: {path}")

    def _delete_platform_file(self) -> None:
        sel = self._file_list.curselection()
        if not sel:
            messagebox.showinfo("File", "Select a platform file first.", parent=self._root)
            return
        i = int(sel[0])
        if i < 0 or i >= len(self._file_ids):
            return
        fid = self._file_ids[i]
        if not messagebox.askyesno(
            "Delete file",
            f"Delete file {fid} from OpenAI?",
            parent=self._root,
        ):
            return
        try:
            delete_file(fid)
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        self._refresh_files()

    def _attach_file(self) -> None:
        vs = self._selected_vs_id()
        if not vs:
            messagebox.showinfo("Attach", "Select a vector store on the left first.", parent=self._root)
            return
        sel = self._file_list.curselection()
        if not sel:
            messagebox.showinfo("Attach", "Select a platform file to attach.", parent=self._root)
            return
        i = int(sel[0])
        fid = self._file_ids[i]
        try:
            attach_file_to_vector_store(vs, fid)
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        self._refresh_vs_files()

    def _detach_vs_file(self) -> None:
        vs = self._selected_vs_id()
        if not vs:
            return
        sel = self._vsf_list.curselection()
        if not sel:
            messagebox.showinfo("Remove", "Select a file in the vector store list.", parent=self._root)
            return
        i = int(sel[0])
        if i < 0 or i >= len(self._vs_file_ids):
            return
        fid = self._vs_file_ids[i]
        fn = (
            self._vs_file_names[i]
            if i < len(self._vs_file_names)
            else None
        )
        label = f"{fn} ({fid})" if fn else fid
        if not messagebox.askyesno(
            "Remove file",
            f"Remove {label} from vector store {vs}?",
            parent=self._root,
        ):
            return
        try:
            delete_vector_store_file(vs, fid)
        except OpenAIAdminError as e:
            self._set_err(str(e))
            return
        self._refresh_vs_files()

    def _save_bot1_selection(self) -> None:
        sel = self._bot1_list.curselection()
        ids = [self._bot1_ids[i] for i in sel if 0 <= i < len(self._bot1_ids)]
        ui = load_bot1_ui_settings()
        ui.vector_store_ids = ids
        save_bot1_ui_settings(ui)
        self._set_err(f"Saved {len(ids)} vector store id(s) for Bot 1 file_search.")

    def _save_bot2_selection(self) -> None:
        sel = self._bot2_list.curselection()
        ids = [self._bot2_ids[i] for i in sel if 0 <= i < len(self._bot2_ids)]
        ui = load_bot2_ui_settings()
        ui.vector_store_ids = ids
        save_bot2_ui_settings(ui)
        self._set_err(f"Saved {len(ids)} vector store id(s) for Bot 2 file_search.")
