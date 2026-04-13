"""Modal progress UI for session deletion (individual steps + overall bar)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.ui.material_theme import MaterialColors


class SessionDeleteProgressDialog(tk.Toplevel):
    """
    Shows overall progress and per-step status while deleting a session.
    ``on_step(i, total, label, phase)`` drives updates; phase is begin|end|error.
    """

    def __init__(
        self,
        master: tk.Tk,
        *,
        step_labels: tuple[str, ...],
        latin_font: str,
    ) -> None:
        super().__init__(master)
        self._labels = step_labels
        self._latin = latin_font
        self._total = len(step_labels)
        self.title("Deleting session")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(bg=MaterialColors.surface)

        outer = ttk.Frame(self, padding=(18, 14, 18, 14))
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Deleting session data — please wait.",
            font=(latin_font, 11, "bold"),
        ).pack(anchor="w")

        self._overall_var = tk.StringVar(value=f"Overall: 0 / {self._total} steps")
        ttk.Label(outer, textvariable=self._overall_var, font=(latin_font, 9)).pack(
            anchor="w", pady=(8, 4)
        )

        self._progress = ttk.Progressbar(
            outer,
            mode="determinate",
            maximum=self._total,
            length=420,
        )
        self._progress.pack(fill="x", pady=(0, 12))

        sep = ttk.Label(outer, text="Steps:", font=(latin_font, 9, "bold"))
        sep.pack(anchor="w", pady=(0, 4))

        rows = ttk.Frame(outer)
        rows.pack(fill="x")
        self._row_widgets: list[ttk.Label] = []
        for i, lab in enumerate(step_labels):
            lbl = ttk.Label(
                rows,
                text=self._line_text(i, "pending", lab),
                font=(latin_font, 9),
                wraplength=440,
                justify="left",
            )
            lbl.pack(anchor="w", pady=1)
            self._row_widgets.append(lbl)

        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 460)
        h = self.winfo_reqheight()
        try:
            mx = master.winfo_rootx() + (master.winfo_width() - w) // 2
            my = master.winfo_rooty() + (master.winfo_height() - h) // 2
            self.geometry(f"{w}x{h}+{max(0, mx)}+{max(0, my)}")
        except tk.TclError:
            self.geometry(f"{w}x{h}")

    def _line_text(self, _index: int, state: str, label: str) -> str:
        sym = {"pending": "○", "active": "◐", "done": "✓", "error": "✗"}.get(state, "○")
        return f"{sym}  {label}"

    def notify_step(self, index: int, total: int, _label: str, phase: str) -> None:
        """Update UI for one step; safe to call from main thread."""
        if index < 0 or index >= len(self._row_widgets):
            return
        lab = self._labels[index]
        if phase == "begin":
            st = "active"
            self._progress["value"] = index
            self._overall_var.set(f"Overall: step {index + 1} of {total} — in progress…")
        elif phase == "end":
            st = "done"
            self._progress["value"] = index + 1
            self._overall_var.set(f"Overall: {index + 1} / {total} steps completed")
        elif phase == "error":
            st = "error"
            self._overall_var.set(f"Overall: error at step {index + 1} of {total}")
        else:
            st = "pending"
        self._row_widgets[index].configure(text=self._line_text(index, st, lab))
        self.update_idletasks()
        self.update()

    def set_complete(self) -> None:
        self._progress["value"] = self._total
        self._overall_var.set(f"Overall: {self._total} / {self._total} steps completed")
