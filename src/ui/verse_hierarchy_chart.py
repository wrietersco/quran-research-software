"""Interactive hierarchical graph (matplotlib + NetworkX) for verse → words → roots → headings."""

from __future__ import annotations

import re
import textwrap
from collections import defaultdict

import matplotlib.axes
import matplotlib.text
import networkx as nx
from matplotlib.colors import to_rgba

from src.db.verse_hierarchy import VerseWordNode
from src.ui.arabic_display import configure_matplotlib_arabic_font, shape_arabic_display
from src.ui.lexicon_display import heading_display_label
from src.ui.material_theme import MaterialColors

_ARABIC_FONT_FAMILY = configure_matplotlib_arabic_font()

# 0 verse, 1 word, 2 morph segment, 3 root, 4 heading, 5 definition leaf (green)
_LAYER_COLORS = ("#0b3d5c", "#154f7c", "#1a6f8c", "#6c3483", "#a04000", "#145a32")
_LAYER_FONTSIZE = (11, 10, 9.0, 10, 8.5, 7.0)
_DEF_Y_GAP = 0.42
_MAX_DEFINITION_CHARS = 10000
# Minimum horizontal gap in data coords between heading boxes (increased for Arabic)
_HEADING_MIN_DX = 0.52
_HEADING_ROW_HEIGHT = 0.42
_HEADINGS_PER_ROW = 7
# Vertical offset amplitude (data coords) so siblings in a layer zig-zag instead of a flat line
_ZIGZ_WORD = 0.16
_ZIGZ_MORPH = 0.11
_ZIGZ_ROOT = 0.14
_ZIGZ_HEADING = 0.09
# Shown on the graph at each definition leaf; full text is shown on leaf click only.
_LEAF_NODE_HINT = "Definition"


def build_verse_digraph(
    surah: int, ayah: int, words: list[VerseWordNode]
) -> tuple[nx.DiGraph, dict[str, str], dict[str, str], dict[str, str]]:
    """
    Morph segments (layer 2) under each word, then root (3), heading (4), definition (5).
    ``leaf_full_text`` maps leaf id → full definition for click handler.
    """
    G = nx.DiGraph()
    short: dict[str, str] = {}
    full: dict[str, str] = {}
    leaf_full_text: dict[str, str] = {}

    root = "verse"
    G.add_node(root, layer=0)
    label0 = f"Surah {surah} · Ayah {ayah}"
    short[root] = label0
    full[root] = label0

    for i, w in enumerate(words):
        wid = f"w{i}"
        G.add_node(wid, layer=1)
        G.add_edge(root, wid)
        wtext = f"{w.word_no}. {w.token_uthmani}"
        short[wid] = wtext
        full[wid] = wtext

        for j, k in enumerate(w.kalimat):
            mid = f"m{i}_{j}"
            G.add_node(mid, layer=2)
            G.add_edge(wid, mid)
            pos = (k.pos or "").strip()
            m_short = k.surface if not pos else f"{k.surface} [{pos}]"
            m_full = m_short
            short[mid] = m_short
            full[mid] = m_full

        if w.root_id is not None and w.root_word:
            rid = f"r{i}"
            G.add_node(rid, layer=3)
            G.add_edge(wid, rid)
            rtext = f"Root: {w.root_word}"
            short[rid] = rtext
            full[rid] = rtext
            if w.entry_headings:
                for h in w.entry_headings:
                    hid = f"h{i}_{h.seq}"
                    G.add_node(hid, layer=4)
                    G.add_edge(rid, hid)
                    clean = heading_display_label(h.label)
                    htext = clean if clean.strip() else f"Entry {h.seq}"
                    short[hid] = htext
                    full[hid] = htext
                    did = f"d{i}_{h.seq}"
                    G.add_node(did, layer=5)
                    G.add_edge(hid, did)
                    short[did] = _LEAF_NODE_HINT
                    full[did] = _LEAF_NODE_HINT
                    raw_def = (h.definition or "").strip()
                    leaf_full_text[did] = (
                        raw_def if len(raw_def) <= _MAX_DEFINITION_CHARS
                        else raw_def[: _MAX_DEFINITION_CHARS - 1] + "…"
                    )
            else:
                eid = f"e{i}"
                G.add_node(eid, layer=4)
                G.add_edge(rid, eid)
                short[eid] = "(no headings)"
                full[eid] = "(no lexicon headings for this root)"
        elif w.root_id is not None:
            rid = f"r{i}"
            G.add_node(rid, layer=3)
            G.add_edge(wid, rid)
            short[rid] = f"(root id {w.root_id})"
            full[rid] = f"Missing lexicon_roots row for root id {w.root_id}"
        else:
            rid = f"nr{i}"
            G.add_node(rid, layer=3)
            G.add_edge(wid, rid)
            short[rid] = "(no root)"
            full[rid] = "(no mapped root)"

    return G, short, full, leaf_full_text


def layout_top_down(
    G: nx.DiGraph, labels: dict[str, str]
) -> dict[str, tuple[float, float]]:
    """Multipartite layers, root at top; wide scale; then spread headings under each root."""
    pos: dict[str, tuple[float, float]] = {}
    raw = nx.multipartite_layout(
        G, subset_key="layer", align="horizontal", scale=3.2
    )
    for k, v in raw.items():
        pos[k] = (float(v[0]), -float(v[1]))
    reposition_heading_clusters(G, pos, labels)
    apply_zigzag_stagger(G, pos)
    place_definition_nodes(G, pos)
    apply_zigzag_definition_layer(G, pos)
    mirror_positions_rtl(pos)
    align_word_columns_rtl(G, pos)
    recenter_verse_above_words(G, pos)
    return pos


def mirror_positions_rtl(pos: dict[str, tuple[float, float]]) -> None:
    """Mirror horizontally so the tree reads from the right (verse side) like RTL text."""
    if not pos:
        return
    xs = [p[0] for p in pos.values()]
    lo, hi = min(xs), max(xs)
    for k in pos:
        x, y = pos[k]
        pos[k] = (lo + hi - x, y)


def align_word_columns_rtl(G: nx.DiGraph, pos: dict[str, tuple[float, float]]) -> None:
    """
    Force word nodes into strict right-to-left order: word 1 rightmost, then 2, 3, …
    Each word's subtree (root + headings) moves horizontally with it.
    """
    words = sorted(
        [n for n in G.nodes() if G.nodes[n]["layer"] == 1],
        key=_word_sort_key,
    )
    if len(words) <= 1:
        return
    old_x = {w: pos[w][0] for w in words}
    xs = list(old_x.values())
    lo, hi = min(xs), max(xs)
    span = hi - lo
    n = len(words)
    step = span / (n - 1) if n > 1 else 0.0
    # w0 → word 1 at right (hi); w_{n-1} → word n at left (lo)
    for i, w in enumerate(words):
        target_x = hi - i * step
        delta = target_x - old_x[w]
        sub = nx.descendants(G, w) | {w}
        for node in sub:
            x, y = pos[node]
            pos[node] = (x + delta, y)


def recenter_verse_above_words(G: nx.DiGraph, pos: dict[str, tuple[float, float]]) -> None:
    """Keep the verse node centered over the word row after column shifts."""
    if "verse" not in pos:
        return
    layer1 = [n for n in G.nodes() if G.nodes[n]["layer"] == 1]
    if not layer1:
        return
    xs = [pos[w][0] for w in layer1]
    cx = (min(xs) + max(xs)) / 2.0
    _, y = pos["verse"]
    pos["verse"] = (cx, y)


def _word_sort_key(nid: str) -> tuple[int, str]:
    m = re.match(r"^w(\d+)$", nid)
    return (int(m.group(1)), nid) if m else (0, nid)


def _morph_sort_key(nid: str) -> tuple[int, int, str]:
    m = re.match(r"^m(\d+)_(\d+)$", nid)
    if m:
        return (int(m.group(1)), int(m.group(2)), nid)
    return (0, 0, nid)


def _root_sort_key(nid: str) -> tuple[int, str]:
    if nid.startswith("nr") and nid[2:].isdigit():
        return (int(nid[2:]), nid)
    if nid.startswith("r") and nid[1:].isdigit():
        return (int(nid[1:]), nid)
    return (0, nid)


def apply_zigzag_stagger(G: nx.DiGraph, pos: dict[str, tuple[float, float]]) -> None:
    """
    Nudge nodes off a perfectly flat row: alternate up/down by index so the chart
    reads in a zig-zag instead of rigid horizontal bands.
    """
    max_layer = max((G.nodes[n]["layer"] for n in G.nodes()), default=0)

    for layer in range(max_layer + 1):
        nodes = [n for n in G.nodes() if G.nodes[n]["layer"] == layer]
        if len(nodes) <= 1:
            continue

        if layer == 4:
            # Each heading row zig-zags independently (group by y band)
            bands: dict[float, list[str]] = defaultdict(list)
            for n in nodes:
                bands[round(pos[n][1], 3)].append(n)
            for yb in sorted(bands.keys(), reverse=True):
                row = sorted(bands[yb], key=lambda n: pos[n][0])
                for i, n in enumerate(row):
                    dy = _ZIGZ_HEADING * (1 if i % 2 == 0 else -1)
                    x, y = pos[n]
                    pos[n] = (x, y + dy)
            continue

        if layer == 5:
            continue

        if layer == 1:
            nodes.sort(key=_word_sort_key)
            amp = _ZIGZ_WORD
        elif layer == 2:
            nodes.sort(key=_morph_sort_key)
            amp = _ZIGZ_MORPH
        elif layer == 3:
            nodes.sort(key=_root_sort_key)
            amp = _ZIGZ_ROOT
        else:
            nodes.sort(key=lambda n: pos[n][0])
            amp = 0.11

        for i, n in enumerate(nodes):
            dy = amp * (1 if i % 2 == 0 else -1)
            x, y = pos[n]
            pos[n] = (x, y + dy)


def reposition_heading_clusters(
    G: nx.DiGraph,
    pos: dict[str, tuple[float, float]],
    labels: dict[str, str],
) -> None:
    """
    Place layer-4 (heading) nodes in rows centered under their root parent so labels
    do not sit on a single overcrowded line.
    """
    layer4 = [n for n in G.nodes() if G.nodes[n]["layer"] == 4]
    by_parent: dict[str, list[str]] = {}
    for n in layer4:
        preds = list(G.predecessors(n))
        if not preds:
            continue
        p = preds[0]
        by_parent.setdefault(p, []).append(n)

    for p, chs in by_parent.items():
        if p not in pos:
            continue
        px, py_parent = pos[p]
        # Stable order: by seq in id (h{i}_{seq})
        def _sort_key(nid: str) -> tuple[int, str]:
            if "_" in nid:
                parts = nid.split("_", 1)
                try:
                    return (int(parts[1]), nid)
                except ValueError:
                    return (0, nid)
            return (0, nid)

        chs_sorted = sorted(chs, key=_sort_key)
        y_base = min(pos[c][1] for c in chs_sorted) if chs_sorted else py_parent

        rows: list[list[str]] = []
        for i in range(0, len(chs_sorted), _HEADINGS_PER_ROW):
            rows.append(chs_sorted[i : i + _HEADINGS_PER_ROW])

        for ri, row in enumerate(rows):
            y = y_base - ri * _HEADING_ROW_HEIGHT
            m = len(row)
            if m == 0:
                continue
            lengths = [len(labels.get(n, "")) for n in row]
            max_len = max(lengths) if lengths else 10
            dx = max(_HEADING_MIN_DX, 0.12 + 0.0045 * min(max_len, 120))
            total = (m - 1) * dx
            sx = px - total / 2
            for j, node in enumerate(row):
                pos[node] = (sx + j * dx, y)

    # Resolve overlaps between clusters: push right when two boxes would collide on x
    if layer4:
        layer4_sorted = sorted(layer4, key=lambda n: pos[n][0])
        min_gap = _HEADING_MIN_DX * 0.85
        for _ in range(len(layer4_sorted) * 2):
            moved = False
            for i in range(1, len(layer4_sorted)):
                a, b = layer4_sorted[i - 1], layer4_sorted[i]
                x_a, x_b = pos[a][0], pos[b][0]
                if x_b - x_a < min_gap:
                    shift = min_gap - (x_b - x_a)
                    for k in range(i, len(layer4_sorted)):
                        n = layer4_sorted[k]
                        pos[n] = (pos[n][0] + shift, pos[n][1])
                    moved = True
                    break
            if not moved:
                break


def place_definition_nodes(G: nx.DiGraph, pos: dict[str, tuple[float, float]]) -> None:
    """Place each definition leaf (layer 5) directly under its heading parent."""
    for n in G.nodes():
        if G.nodes[n].get("layer") != 5:
            continue
        preds = list(G.predecessors(n))
        if not preds:
            continue
        h = preds[0]
        if h not in pos:
            continue
        hx, hy = pos[h]
        pos[n] = (hx, hy - _DEF_Y_GAP)


def apply_zigzag_definition_layer(
    G: nx.DiGraph, pos: dict[str, tuple[float, float]]
) -> None:
    """Light zig-zag on definition rows after they are placed under headings."""
    nodes = [n for n in G.nodes() if G.nodes[n]["layer"] == 5]
    if len(nodes) <= 1:
        return
    bands: dict[float, list[str]] = defaultdict(list)
    for n in nodes:
        bands[round(pos[n][1], 3)].append(n)
    for yb in sorted(bands.keys(), reverse=True):
        row = sorted(bands[yb], key=lambda n: pos[n][0])
        for i, n in enumerate(row):
            dy = 0.065 * (1 if i % 2 == 0 else -1)
            x, y = pos[n]
            pos[n] = (x, y + dy)


def subtree_highlight_nodes(G: nx.DiGraph, nid: str) -> set[str]:
    """Ancestors, descendants, and the node itself — the relevant subtree in a tree."""
    return {nid} | nx.ancestors(G, nid) | nx.descendants(G, nid)


def _wrap_label(text: str, layer: int) -> str:
    # Wrap logical string first; reshape each line for joining + RTL visual order.
    # Avoid breaking inside Arabic tokens: break_long_words=False.
    if layer >= 5:
        width = 52
    elif layer <= 2:
        width = 26
    else:
        width = 20
    lines = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not lines:
        return shape_arabic_display(text)
    return "\n".join(shape_arabic_display(line) for line in lines)


def draw_verse_chart(
    ax: matplotlib.axes.Axes,
    G: nx.DiGraph,
    pos: dict[str, tuple[float, float]],
    display_labels: dict[str, str],
    *,
    highlight: set[str] | None = None,
    focus: str | None = None,
) -> tuple[list[str], dict[str, matplotlib.text.Text]]:
    """
    Draw edges and rounded text boxes (no fixed circles) so full labels stay inside boxes.
    If ``highlight`` is set, nodes/edges outside that set are dimmed; ``focus`` gets a gold ring.
    Returns node order and Text artists for hit-testing.
    """
    ax.clear()
    ax.set_facecolor(MaterialColors.surface)
    ax.set_aspect("auto")
    ax.axis("off")

    nodelist = list(G.nodes())
    texts: dict[str, matplotlib.text.Text] = {}

    edges = list(G.edges())
    if highlight is not None:
        dim_e = [
            (u, v)
            for u, v in edges
            if not (u in highlight and v in highlight)
        ]
        hi_e = [
            (u, v)
            for u, v in edges
            if u in highlight and v in highlight
        ]
        for u, v in dim_e:
            x1, y1 = pos[u]
            x2, y2 = pos[v]
            ax.plot(
                [x1, x2],
                [y1, y2],
                color="#d5d8dc",
                linewidth=1.0,
                zorder=1,
                alpha=0.42,
                solid_capstyle="round",
            )
        for u, v in hi_e:
            x1, y1 = pos[u]
            x2, y2 = pos[v]
            ax.plot(
                [x1, x2],
                [y1, y2],
                color="#1a5276",
                linewidth=2.8,
                zorder=2,
                alpha=0.95,
                solid_capstyle="round",
            )
    else:
        for u, v in edges:
            x1, y1 = pos[u]
            x2, y2 = pos[v]
            ax.plot(
                [x1, x2],
                [y1, y2],
                color="#95a5a6",
                linewidth=1.4,
                zorder=1,
                alpha=0.9,
                solid_capstyle="round",
            )

    for n in nodelist:
        layer = G.nodes[n]["layer"]
        color = _LAYER_COLORS[min(layer, len(_LAYER_COLORS) - 1)]
        fs = _LAYER_FONTSIZE[min(layer, len(_LAYER_FONTSIZE) - 1)]
        raw = display_labels.get(n, n)
        wrapped = _wrap_label(raw, layer)
        x, y = pos[n]

        if highlight is not None and n not in highlight:
            face = to_rgba(color, 0.24)
            text_c = "#aeb6bf"
            ec = "#e5e8e8"
            lw = 0.9
            z = 2
        else:
            face = color
            text_c = "white"
            is_focus = focus is not None and n == focus
            ec = "#f7dc6f" if is_focus else "#1c2833"
            lw = 2.8 if is_focus else 1.2
            z = 5 if is_focus else 3

        t = ax.text(
            x,
            y,
            wrapped,
            ha="center",
            va="center",
            fontsize=fs,
            color=text_c,
            fontweight="bold",
            fontfamily=_ARABIC_FONT_FAMILY,
            zorder=z,
            bbox={
                "boxstyle": "round,pad=0.45,rounding_size=0.2",
                "facecolor": face,
                "edgecolor": ec,
                "linewidth": lw,
            },
            clip_on=False,
        )
        texts[n] = t

    ax.autoscale_view()
    xl, xr = ax.get_xlim()
    yb, yt = ax.get_ylim()
    pw = xr - xl
    ph = yt - yb
    pad_x = 0.06 * max(pw, 1e-6)
    pad_y = 0.08 * max(ph, 1e-6)
    ax.set_xlim(xl - pad_x, xr + pad_x)
    ax.set_ylim(yb - pad_y, yt + pad_y)

    return nodelist, texts


class VerseHierarchyChart:
    """Embeddable matplotlib figure with zoom/pan toolbar and click-to-select nodes."""

    def __init__(self, parent, on_pick) -> None:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure

        self._on_pick = on_pick
        self._nodelist: list[str] = []
        self._full_labels: dict[str, str] = {}
        self._pos: dict[str, tuple[float, float]] = {}
        self._text_artists: dict[str, matplotlib.text.Text] = {}
        self._graph: nx.DiGraph | None = None
        self._short_labels: dict[str, str] = {}
        self._leaf_full_text: dict[str, str] = {}

        self.figure = Figure(figsize=(12, 8), dpi=100, facecolor=MaterialColors.surface)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor(MaterialColors.surface)
        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, parent, pack_toolbar=False)
        self.toolbar.pack(side="bottom", fill="x")

        self.canvas.mpl_connect("button_press_event", self._handle_click)
        self.clear()

    def clear(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor(MaterialColors.surface)
        self.figure.patch.set_facecolor(MaterialColors.surface)
        self.ax.axis("off")
        self.ax.text(
            0.5,
            0.5,
            "Load a verse to see the graph.\n\nTip: use the toolbar to zoom and pan.",
            ha="center",
            va="center",
            transform=self.ax.transAxes,
            fontsize=11,
            color=MaterialColors.on_surface_variant,
        )
        self._nodelist = []
        self._full_labels = {}
        self._pos = {}
        self._text_artists = {}
        self._graph = None
        self._short_labels = {}
        self._leaf_full_text = {}
        self.canvas.draw_idle()

    def render(self, surah: int, ayah: int, words: list[VerseWordNode]) -> None:
        if not words:
            self.clear()
            return

        G, short, full, leaf_full_text = build_verse_digraph(surah, ayah, words)
        self._graph = G
        self._short_labels = short
        self._leaf_full_text = leaf_full_text
        self._pos = layout_top_down(G, short)
        self._full_labels = full
        self._nodelist, self._text_artists = draw_verse_chart(
            self.ax, G, self._pos, short, highlight=None, focus=None
        )
        # Avoid tight_layout: it can clip wide rounded label boxes
        self.figure.subplots_adjust(left=0.02, right=0.98, top=0.97, bottom=0.03)
        # Synchronous draw so Text.get_window_extent / contains() work on first click
        self.canvas.draw()

    def _handle_click(self, event) -> None:
        if event.inaxes != self.ax or event.xdata is None:
            return
        if event.button != 1:
            return
        if self.toolbar.mode != "":
            return

        # Top-most label wins (later zorder)
        for nid in reversed(self._nodelist):
            t = self._text_artists.get(nid)
            if t is None:
                continue
            inside, _ = t.contains(event)
            if inside:
                body = self._leaf_full_text.get(nid)
                heading_ctx: str | None = None
                if body is not None and self._graph is not None:
                    preds = list(self._graph.predecessors(nid))
                    if preds:
                        heading_ctx = self._full_labels.get(preds[0])
                self._on_pick(
                    nid,
                    self._full_labels.get(nid, nid),
                    body,
                    heading_ctx,
                )
                if self._graph is not None:
                    h = subtree_highlight_nodes(self._graph, nid)
                    self._nodelist, self._text_artists = draw_verse_chart(
                        self.ax,
                        self._graph,
                        self._pos,
                        self._short_labels,
                        highlight=h,
                        focus=nid,
                    )
                    self.figure.subplots_adjust(
                        left=0.02, right=0.98, top=0.97, bottom=0.03
                    )
                    self.canvas.draw()
                return
