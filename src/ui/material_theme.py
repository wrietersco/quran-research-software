"""Material Design 3–inspired colors and ttk styling for the desktop explorer."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any


class MaterialColors:
    """Semantic palette (light)."""

    # Surfaces
    surface = "#F6F7FB"
    surface_dim = "#E8ECF4"
    surface_container = "#FFFFFF"
    surface_container_high = "#EEF1F8"
    # Primary — teal (readable with Arabic content)
    primary = "#006B5E"
    on_primary = "#FFFFFF"
    primary_container = "#B2EBE0"
    on_primary_container = "#00201C"
    # Secondary — indigo
    secondary = "#3D5AFE"
    on_secondary = "#FFFFFF"
    secondary_container = "#E0E7FF"
    on_secondary_container = "#121C5C"
    # Tertiary / accent
    tertiary = "#7B1FA2"
    on_surface = "#1B1B1F"
    on_surface_variant = "#44474E"
    outline = "#C4C6D0"
    error = "#BA1A1A"
    on_error_container = "#410002"
    success = "#1B5E20"
    # Selection / focus
    selection = "#C8E6E9"
    selection_text = "#003731"


def apply_material_theme(
    root: tk.Tk,
    *,
    latin_family: str,
    arabic_family: str,
    style: ttk.Style | None = None,
) -> dict[str, Any]:
    """
    Configure global ttk styles and root background.
    Returns a dict of font tuples for convenience: body, tab, bold, arabic_body, browse.
    """
    st = style or tk.ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass

    C = MaterialColors
    body = 11
    tab = 11
    arabic_size = 15
    browse_size = 12

    f_ar = tkfont.Font(family=arabic_family, size=arabic_size)
    line = max(int(f_ar.metrics("linespace")), 18)
    verse_row_h = max(line + 10, 38)
    f_browse = tkfont.Font(family=arabic_family, size=browse_size)
    browse_line = max(int(f_browse.metrics("linespace")), 16)
    browse_row_h = max(browse_line + 8, 30)

    root.configure(bg=C.surface)
    st.configure("TFrame", background=C.surface)
    st.configure("TNotebook", background=C.surface, borderwidth=0)
    st.configure(
        "TNotebook.Tab",
        padding=[16, 10],
        font=(latin_family, tab),
        background=C.surface_dim,
        foreground=C.on_surface,
    )
    st.map(
        "TNotebook.Tab",
        background=[("selected", C.surface_container)],
        foreground=[("selected", C.primary)],
    )
    st.configure("TLabel", background=C.surface, font=(latin_family, body), foreground=C.on_surface)
    st.configure("TButton", font=(latin_family, body))
    st.configure("TSpinbox", font=(latin_family, body), fieldbackground=C.surface_container)
    st.configure("TCombobox", font=(latin_family, body), fieldbackground=C.surface_container)
    st.configure("TPanedwindow", background=C.surface)
    st.configure("TLabelframe", background=C.surface, foreground=C.primary)
    st.configure("TLabelframe.Label", background=C.surface, foreground=C.primary, font=(latin_family, body, "bold"))
    st.configure(
        "Treeview",
        font=(arabic_family, browse_size),
        rowheight=browse_row_h,
        background=C.surface_container,
        fieldbackground=C.surface_container,
        foreground=C.on_surface,
        borderwidth=0,
    )
    st.configure(
        "Treeview.Heading",
        font=(latin_family, tab, "bold"),
        background=C.surface_dim,
        foreground=C.on_surface,
        relief="flat",
        padding=(8, 10),
    )
    st.map("Treeview", background=[("selected", C.selection)], foreground=[("selected", C.selection_text)])
    st.configure(
        "Verse.Treeview",
        font=(arabic_family, arabic_size),
        rowheight=verse_row_h,
        background=C.surface_container,
        fieldbackground=C.surface_container,
        foreground=C.on_surface,
    )
    st.configure(
        "Verse.Treeview.Heading",
        font=(latin_family, tab, "bold"),
        background=C.surface_dim,
        foreground=C.on_surface,
        relief="flat",
        padding=(8, 10),
    )
    st.map("Verse.Treeview", background=[("selected", C.selection)], foreground=[("selected", C.selection_text)])
    st.configure(
        "Browse.Treeview",
        font=(arabic_family, browse_size),
        rowheight=browse_row_h,
        background=C.surface_container,
        fieldbackground=C.surface_container,
        foreground=C.on_surface,
    )
    st.configure(
        "Browse.Treeview.Heading",
        font=(latin_family, tab, "bold"),
        background=C.surface_dim,
        padding=(6, 8),
    )
    st.map("Browse.Treeview", background=[("selected", C.selection)], foreground=[("selected", C.selection_text)])
    st.configure("Horizontal.TScrollbar", troughcolor=C.surface_dim, borderwidth=0)
    st.configure("Vertical.TScrollbar", troughcolor=C.surface_dim, borderwidth=0)

    # Card panels, hero strip, and primary actions (Question refiner and similar flows)
    st.configure("Card.TFrame", background=C.surface_container)
    st.configure("Hero.TFrame", background=C.primary_container)
    st.configure(
        "HeroTitle.TLabel",
        background=C.primary_container,
        foreground=C.on_primary_container,
        font=(latin_family, 17, "bold"),
    )
    st.configure(
        "HeroMeta.TLabel",
        background=C.primary_container,
        foreground=C.primary,
        font=(latin_family, 10),
    )
    st.configure(
        "HeroRq.TLabel",
        background=C.primary_container,
        foreground=C.on_surface,
        font=(latin_family, 10),
    )
    st.configure("Card.TLabelframe", background=C.surface_container, foreground=C.on_surface)
    st.configure(
        "Card.TLabelframe.Label",
        background=C.surface_container,
        foreground=C.on_surface_variant,
        font=(latin_family, 10, "bold"),
    )
    st.configure(
        "Accent.TButton",
        background=C.primary,
        foreground=C.on_primary,
        relief="flat",
        borderwidth=0,
        focusthickness=3,
        focuscolor=C.primary_container,
        padding=(14, 10),
    )
    st.map(
        "Accent.TButton",
        background=[
            ("disabled", C.surface_dim),
            ("pressed", "#004D43"),
            ("active", "#005348"),
        ],
        foreground=[("disabled", C.on_surface_variant)],
    )
    st.configure(
        "SectionHeading.TLabel",
        background=C.surface_container,
        foreground=C.on_surface,
        font=(latin_family, 11, "bold"),
    )
    st.configure(
        "Hint.TLabel",
        background=C.surface_container,
        foreground=C.on_surface_variant,
        font=(latin_family, 9),
    )
    st.configure(
        "TProgressbar",
        troughcolor=C.surface_dim,
        background=C.primary,
        borderwidth=0,
        thickness=6,
    )
    st.configure(
        "Status.TLabel",
        background=C.surface_container,
        foreground=C.on_surface_variant,
        font=(latin_family, 9),
    )
    st.configure("PipelineBanner.TFrame", background=C.surface_container_high)
    st.configure(
        "PipelineBannerTitle.TLabel",
        background=C.surface_container_high,
        foreground=C.primary,
        font=(latin_family, 11, "bold"),
    )
    st.configure(
        "PipelineBannerBody.TLabel",
        background=C.surface_container_high,
        foreground=C.on_surface_variant,
        font=(latin_family, 9),
    )
    st.configure(
        "Disclosure.TButton",
        relief="flat",
        borderwidth=0,
        background=C.surface_container,
        foreground=C.primary,
        font=(latin_family, 10),
        padding=(0, 8),
        focuscolor=C.primary_container,
    )
    st.map(
        "Disclosure.TButton",
        background=[("active", C.surface_container_high), ("pressed", C.surface_dim)],
    )
    st.configure(
        "ErrorHint.TLabel",
        background=C.surface_container,
        foreground=C.error,
        font=(latin_family, 9),
    )

    return {
        "latin": latin_family,
        "arabic": arabic_family,
        "body": body,
        "tab": tab,
        "arabic_size": arabic_size,
        "browse_size": browse_size,
    }


def style_tk_listbox(
    listbox: tk.Listbox,
    *,
    latin_family: str,
    size: int = 10,
) -> None:
    C = MaterialColors
    listbox.configure(
        font=(latin_family, size),
        bg=C.surface_container,
        fg=C.on_surface,
        selectbackground=C.primary,
        selectforeground=C.on_primary,
        activestyle="none",
        highlightthickness=0,
        borderwidth=1,
        relief="flat",
    )


def style_tk_text_readonly(
    widget: tk.Text,
    *,
    family: str,
    size: int,
    monospace: bool = False,
    subtle: bool = False,
) -> None:
    C = MaterialColors
    bg = C.surface_container_high if subtle else C.surface_container
    widget.configure(
        font=("Consolas", size) if monospace else (family, size),
        bg=bg,
        fg=C.on_surface,
        insertbackground=C.primary,
        relief="flat",
        highlightthickness=1,
        highlightbackground=C.outline,
        highlightcolor=C.primary,
        padx=12,
        pady=12,
    )


def style_tk_text_input(widget: tk.Text, *, family: str, size: int) -> None:
    C = MaterialColors
    widget.configure(
        font=(family, size),
        bg=C.surface_container,
        fg=C.on_surface,
        insertbackground=C.primary,
        relief="flat",
        highlightthickness=1,
        highlightbackground=C.outline,
        highlightcolor=C.primary,
        padx=10,
        pady=10,
    )
