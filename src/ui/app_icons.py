"""Load Material-style PNG icons (see scripts/build_ui_icons.py) for ttk widgets."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

_ICONS_DIR = Path(__file__).resolve().parent / "icons_data"

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None  # type: ignore[misc, assignment]
    ImageTk = None  # type: ignore[misc, assignment]


class AppIconSet:
    """Keeps PhotoImage references alive for Tkinter."""

    def __init__(self, master: tk.Misc) -> None:
        self._master = master
        self._cache: dict[str, tk.PhotoImage] = {}

    def get(self, name: str, *, size: int | None = None) -> tk.PhotoImage | None:
        if name in self._cache:
            return self._cache[name]
        path = _ICONS_DIR / f"{name}.png"
        if not path.is_file():
            return None
        if Image is not None and ImageTk is not None:
            im = Image.open(path).convert("RGBA")
            if size is not None and size != im.width:
                im = im.resize((size, size), Image.Resampling.LANCZOS)
            ph = ImageTk.PhotoImage(im, master=self._master)
        else:
            ph = tk.PhotoImage(master=self._master, file=str(path))
            if size is not None:
                # Without Pillow we cannot resize; use native size
                pass
        self._cache[name] = ph
        return ph
