"""Display helpers for lexicon headings (strip Lane-style '1. =>' / '⇒' prefixes)."""

from __future__ import annotations

import re


def heading_display_label(raw: str) -> str:
    """
    Return the readable part of a stored heading: drop leading ordinals and '=> / ⇒' ladders.

    Examples:
        "1 . 1 . ⇒ بِسْمِ" -> "بِسْمِ"
        "1. => foo" -> "foo"
    """
    if not raw:
        return ""
    s = raw.strip()
    for sep in ("⇒", "=>"):
        if sep in s:
            tail = s.split(sep, 1)[-1].strip()
            if tail:
                return tail
    # "1 . 2 . 3 ." or "1." prefixes without arrow
    t = re.sub(r"^(\d+\s*\.\s*)+", "", s)
    t = re.sub(r"^\d+\.\s*", "", t)
    t = re.sub(r"^[⇒=>\-\s]+", "", t).strip()
    return t if t else s


def entry_dialog_title(seq: int, raw_label: str) -> str:
    """Title for definition popup: cleaned heading, or neutral fallback."""
    clean = heading_display_label(raw_label)
    if clean:
        return clean
    return f"Entry {seq}"
