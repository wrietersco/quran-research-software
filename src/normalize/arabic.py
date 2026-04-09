"""Arabic text normalization for token matching and indexing."""

from __future__ import annotations

import re
import unicodedata

# Tatweel / kashida
_TATWEEL = "\u0640"

# Common alif variants -> bare alif
_ALIF_VARIANTS = {
    "\u0622": "\u0627",  # آ
    "\u0623": "\u0627",  # أ
    "\u0625": "\u0627",  # إ
    "\u0671": "\u0627",  # ٱ
}

# Optional: ya / alif maqsura normalization for matching
_WAW = "\u0648"
_YA = "\u064a"
_ALIF_MAQSURA = "\u0649"


def _strip_diacritics(s: str) -> str:
    out = []
    for ch in s:
        if unicodedata.category(ch) == "Mn":
            continue
        # Arabic diacritic blocks (not always Mn in all Unicode versions)
        o = ord(ch)
        if 0x064B <= o <= 0x065F:
            continue
        if o == 0x0670:  # superscript alif
            continue
        out.append(ch)
    return "".join(out)


def normalize_arabic(text: str, *, unify_alif: bool = True, unify_ta_marbuta: bool = False) -> str:
    """
    Normalize Arabic for DB storage and comparison.

    - NFKC
    - Remove tatweel and combining marks / diacritics
    - Optionally unify alif variants to ا
    - Optionally convert ة -> ه for looser matching
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.replace(_TATWEEL, "")
    s = _strip_diacritics(s)
    if unify_alif:
        for a, b in _ALIF_VARIANTS.items():
            s = s.replace(a, b)
    if unify_ta_marbuta:
        s = s.replace("\u0629", "\u0647")  # ة -> ه
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Single-letter and common proclitics (prefix strip for heuristic root search)
_CLITIC_PREFIXES = (
    "ال",
    "وال",
    "فال",
    "بال",
    "كال",
    "لل",
    "ول",
    "فل",
    "بل",
    "كل",
    "ل",
    "و",
    "ف",
    "ب",
    # Avoid single-letter prefixes beyond common particles; they remove stem-initial radicals.
)


def strip_clitics_prefix(token_plain: str, max_strips: int = 3) -> str:
    """Remove common Arabic prefixes repeatedly (best-effort for mapping heuristics)."""
    s = token_plain
    for _ in range(max_strips):
        changed = False
        for p in _CLITIC_PREFIXES:
            if s.startswith(p) and len(s) > len(p):
                s = s[len(p) :]
                changed = True
                break
        if not changed:
            break
    return s


def canonical_heading(seq: int, heading_raw: str) -> str:
    """
    Replace leading 'N. ⇒' in heading with incremental seq for display keys.
    Keeps remainder of heading (e.g. lemma chain) unchanged.
    """
    if not heading_raw:
        return f"{seq}. ⇒"
    m = re.match(r"^\s*\d+\s*\.\s*⇒\s*(.*)$", heading_raw, flags=re.DOTALL)
    if m:
        rest = m.group(1).strip()
        return f"{seq}. ⇒ {rest}" if rest else f"{seq}. ⇒"
    return f"{seq}. ⇒ {heading_raw.strip()}"
