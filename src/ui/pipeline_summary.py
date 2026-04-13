"""Pipeline Summary tab: per-step token, cost, timing, and charts (steps 1–6)."""

from __future__ import annotations

from dataclasses import dataclass

import tkinter as tk
from tkinter import BOTH, END, VERTICAL, ttk
from tkinter.scrolledtext import ScrolledText

from src.ui.material_theme import MaterialColors, style_mpl_figure


@dataclass
class StepPipelineMetric:
    """Metrics for one completed pipeline step (1–6)."""

    agent_involved: bool
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    models_label: str
    duration_secs: float
    started_at_iso: str
    ended_at_iso: str

    @property
    def total_cost_usd(self) -> float:
        return float(self.input_cost_usd) + float(self.output_cost_usd)

    def row_values(self, step_label: str) -> tuple[str, ...]:
        ag = "yes" if self.agent_involved else "no"
        hms = format_duration_hms(self.duration_secs)
        return (
            step_label,
            ag,
            str(self.input_tokens),
            str(self.output_tokens),
            f"${self.input_cost_usd:.6f}",
            f"${self.output_cost_usd:.6f}",
            f"${self.total_cost_usd:.6f}",
            self.models_label,
            hms,
            self.started_at_iso,
            self.ended_at_iso,
        )


def format_duration_hms(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {sec}s"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


STEP_LABELS: tuple[str, ...] = (
    "1 — Bot 1",
    "2 — Bot 2",
    "3 — Find Verses",
    "4 — Kalimat",
    "5 — Shortlist + synth",
    "6 — Report",
)


class PipelineSummaryPane:
    """Renders Summary sub-tab under Question refiner."""

    def __init__(
        self,
        host: object,
        tab: ttk.Frame,
        *,
        latin_font: str = "Segoe UI",
    ) -> None:
        self._host = host
        self._tab = tab
        self._latin = latin_font
        self._tree: ttk.Treeview | None = None
        self._chart_holder: ttk.Frame | None = None
        self._mpl_canvas = None
        self._notes: ScrolledText | None = None
        self._build()

    def _build(self) -> None:
        lf = (self._latin, 10)
        intro = ttk.Label(
            self._tab,
            text=(
                "Per-step metrics populate when each step finishes successfully "
                "(timings use the wall clock on this computer). Costs for OpenAI steps use "
                "approximate list prices from llm_pricing; Step 5 totals match stored USD in the database."
            ),
            wraplength=780,
            justify=tk.LEFT,
            font=lf,
            foreground=MaterialColors.on_surface_variant,
        )
        intro.pack(anchor="w", padx=8, pady=(8, 4))

        wrap = ttk.Frame(self._tab)
        wrap.pack(fill=BOTH, expand=True, padx=6, pady=4)

        cols = (
            "step",
            "agent",
            "tin",
            "tout",
            "cin",
            "cout",
            "ctot",
            "models",
            "dur",
            "t0",
            "t1",
        )
        self._tree = ttk.Treeview(
            wrap,
            columns=cols,
            show="headings",
            height=8,
            selectmode="browse",
        )
        headings = (
            ("step", "Step"),
            ("agent", "Agent"),
            ("tin", "In tokens"),
            ("tout", "Out tokens"),
            ("cin", "In cost"),
            ("cout", "Out cost"),
            ("ctot", "Total cost"),
            ("models", "Model(s)"),
            ("dur", "Duration"),
            ("t0", "Start"),
            ("t1", "End"),
        )
        widths = (120, 52, 72, 72, 78, 78, 78, 200, 72, 140, 140)
        for i, ((cid, text), w) in enumerate(zip(headings, widths, strict=True)):
            self._tree.heading(cid, text=text)
            anchor = "center" if i >= 1 else "w"
            stretch = i == 7
            self._tree.column(cid, width=w, stretch=stretch, anchor=anchor)
        sy = ttk.Scrollbar(wrap, orient=VERTICAL, command=self._tree.yview)
        sx = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        self._chart_holder = ttk.Labelframe(
            self._tab, text="Charts — cost and tokens by step", padding=(6, 6)
        )
        self._chart_holder.pack(fill=BOTH, expand=True, padx=8, pady=(8, 4))

        nf = ttk.Labelframe(self._tab, text="Notes", padding=(6, 6))
        nf.pack(fill=BOTH, expand=False, padx=8, pady=(0, 8))
        self._notes = ScrolledText(nf, height=4, wrap=tk.WORD, font=("Consolas", 9))
        self._notes.pack(fill=BOTH, expand=True)
        self._notes.insert("1.0", self._default_notes())
        self._notes.configure(state="disabled")

        self._fill_placeholder_rows()

    def _default_notes(self) -> str:
        return (
            "Step 3: local token scan — no LLM. Step 4: refresh loads kalimat rows from the DB (no LLM).\n"
            "Step 6 Load: OpenAI file/vector upload without chat completion — shown as agent=no, zero tokens.\n"
            "Step 6 Write: PARI multi-call report; token counts sum all Responses API completions.\n"
        )

    def _fill_placeholder_rows(self) -> None:
        if self._tree is None:
            return
        for i in self._tree.get_children():
            self._tree.delete(i)
        empty = "—"
        for lab in STEP_LABELS:
            self._tree.insert(
                "",
                END,
                values=(lab, empty, empty, empty, empty, empty, empty, empty, empty, empty, empty),
            )

    def refresh_from_store(self, by_step: dict[int, StepPipelineMetric] | None) -> None:
        if self._tree is None:
            return
        for i in self._tree.get_children():
            self._tree.delete(i)
        data = by_step or {}
        for step_i, lab in enumerate(STEP_LABELS, start=1):
            m = data.get(step_i)
            if m:
                self._tree.insert("", END, values=m.row_values(lab))
            else:
                self._tree.insert(
                    "",
                    END,
                    values=(lab, "—", "—", "—", "—", "—", "—", "—", "—", "—", "—"),
                )
        self._redraw_charts(data)

    def _redraw_charts(self, data: dict[int, StepPipelineMetric]) -> None:
        holder = self._chart_holder
        if holder is None:
            return
        for w in holder.winfo_children():
            w.destroy()
        self._mpl_canvas = None
        if not data:
            ttk.Label(
                holder,
                text="Complete a pipeline step to see cost and token charts.",
                foreground=MaterialColors.on_surface_variant,
            ).pack(anchor="w", pady=6)
            return
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

        steps: list[str] = []
        costs: list[float] = []
        toks_in: list[int] = []
        toks_out: list[int] = []
        for step_i in range(1, 7):
            m = data.get(step_i)
            if not m:
                continue
            steps.append(str(step_i))
            costs.append(m.total_cost_usd)
            toks_in.append(m.input_tokens)
            toks_out.append(m.output_tokens)
        if not steps:
            ttk.Label(holder, text="No recorded steps yet.").pack(anchor="w")
            return

        fig = Figure(figsize=(9.2, 3.6), dpi=100, facecolor=MaterialColors.surface)
        ax_c, ax_t = fig.subplots(1, 2)
        colors = ["#1565c0", "#2e7d32", "#6a1b9a", "#ef6c00", "#c62828", "#00838f"]
        x = range(len(steps))
        ax_c.bar(list(x), costs, color=colors[: len(steps)], alpha=0.88)
        ax_c.set_xticks(list(x))
        ax_c.set_xticklabels([f"S{s}" for s in steps], fontsize=9)
        ax_c.set_ylabel("USD", fontsize=9)
        ax_c.set_title("Total cost by step", fontsize=10)
        ax_c.grid(axis="y", linestyle=":", alpha=0.55)

        ax_t.bar([i - 0.2 for i in x], toks_in, width=0.4, label="Input", color="#3949ab", alpha=0.9)
        ax_t.bar([i + 0.2 for i in x], toks_out, width=0.4, label="Output", color="#00897b", alpha=0.9)
        ax_t.set_xticks(list(x))
        ax_t.set_xticklabels([f"S{s}" for s in steps], fontsize=9)
        ax_t.set_ylabel("Tokens", fontsize=9)
        ax_t.set_title("Tokens by step", fontsize=10)
        ax_t.legend(fontsize=8, loc="upper right")
        ax_t.grid(axis="y", linestyle=":", alpha=0.55)

        fig.tight_layout()
        style_mpl_figure(fig)
        canvas = FigureCanvasTkAgg(fig, master=holder)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)
        self._mpl_canvas = canvas
