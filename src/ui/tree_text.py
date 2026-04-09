"""Wrap long text for multiline ttk.Treeview cells."""

from __future__ import annotations


def wrap_tree_cell(
    text: str,
    *,
    width: int = 44,
    max_lines: int = 6,
) -> str:
    """
    Insert newlines so Treeview rows can show wrapped previews (fixed rowheight must fit).
    """
    if not text:
        return ""
    s = " ".join(str(text).split())
    if len(s) <= width:
        return s
    lines: list[str] = []
    rest = s
    while rest and len(lines) < max_lines:
        if len(rest) <= width:
            lines.append(rest)
            break
        chunk = rest[:width]
        br = chunk.rfind(" ")
        if br > width // 3:
            lines.append(rest[:br].rstrip())
            rest = rest[br + 1 :].lstrip()
        else:
            lines.append(rest[:width])
            rest = rest[width:].lstrip()
    if rest and len(lines) >= max_lines and not lines[-1].endswith("…"):
        lines[-1] = lines[-1].rstrip() + "…"
    return "\n".join(lines)
