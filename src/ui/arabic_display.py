"""Arabic shaping (joining) + RTL display strings and font selection for Matplotlib."""

from __future__ import annotations

import re
from functools import lru_cache

# Arabic + Arabic Supplement + Arabic Extended-A blocks (rough)
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    _HAS_BIDI = True
except ImportError:
    _HAS_BIDI = False


def contains_arabic(text: str) -> bool:
    return bool(_ARABIC_RE.search(text))


def shape_arabic_display(text: str) -> str:
    """
    Reshape + bidi so Arabic letters join and read visually RTL in LTR environments.
    Leaves Latin-only fragments unchanged (still passed through get_display when mixed).
    """
    if not text or not _HAS_BIDI:
        return text
    if not contains_arabic(text):
        return text
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text


@lru_cache(maxsize=1)
def resolve_arabic_font_family() -> str:
    """
    Pick a font with strong Arabic joining support. Prefer bundled/known names on Windows/Linux.
    """
    from matplotlib import font_manager

    # Prefer classical Arabic typefaces with full joining tables
    candidates = (
        "Amiri",
        "Amiri Quran",
        "Scheherazade New",
        "Noto Naskh Arabic",
        "Noto Sans Arabic",
        "Traditional Arabic",
        "Arabic Typesetting",
        "Sakkal Majalla",
        "Segoe UI",
    )
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            return name
    # Substring match (some systems report "Amiri Regular")
    for f in font_manager.fontManager.ttflist:
        n = f.name
        for c in candidates:
            if c.lower() in n.lower():
                return n
    return "sans-serif"


def configure_matplotlib_arabic_font() -> str:
    """Set rcParams once so axes text defaults to an Arabic-capable family."""
    import matplotlib

    fam = resolve_arabic_font_family()
    matplotlib.rcParams["font.family"] = fam
    matplotlib.rcParams["font.sans-serif"] = [fam] + [
        x for x in matplotlib.rcParams["font.sans-serif"] if x != fam
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return fam
