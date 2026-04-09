"""Core Step 5 payload and combination utilities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT
from src.db.corpus_roots import buckwalter_root_to_arabic
from src.db.find_match_words import fetch_token_ids_for_find_match
from src.db.verse_hierarchy import fetch_morpheme_roots_for_token_ids
from src.normalize.arabic import normalize_arabic

_DOC = PROJECT_ROOT / "docs" / "step5-theological-synthesizer-system.md"
_STEP5_OVERRIDE = PROJECT_ROOT / "data" / "chat" / "step5_system_base.txt"

# SQLite INTEGER max (signed 64-bit). Larger combo counts cannot be stored reliably.
_SQLITE_MAX_INT = 9223372036854775807


def _safe_total_combos(entry_counts: list[int]) -> int:
    if not entry_counts:
        return 0
    p = 1
    for n in entry_counts:
        k = max(1, int(n))
        if p > _SQLITE_MAX_INT // k:
            return _SQLITE_MAX_INT
        p *= k
    return p


@dataclass(frozen=True)
class Step5LexiconEntry:
    id: int
    seq: int
    heading: str
    definition: str


@dataclass(frozen=True)
class Step5Unit:
    word_no: int
    kalimah_seq: int
    token_uthmani: str
    morpheme_surface: str
    pos: str | None
    root_arabic: str | None
    root_buckwalter: str | None
    root_id: int
    entries: tuple[Step5LexiconEntry, ...]


@dataclass(frozen=True)
class Step5Manifest:
    units: tuple[Step5Unit, ...]
    total_combos: int


def load_step5_base_instructions() -> str:
    """Full system message: user override file if present, else the Step 5 doc."""
    if _STEP5_OVERRIDE.is_file():
        raw = _STEP5_OVERRIDE.read_text(encoding="utf-8")
        if raw.strip():
            return raw.rstrip("\n")
    if not _DOC.is_file():
        raise FileNotFoundError(
            f"Missing system instructions file: {_DOC}. "
            "Create docs/step5-theological-synthesizer-system.md."
        )
    return _DOC.read_text(encoding="utf-8")


def save_step5_base_instructions(text: str) -> None:
    t = (text or "").strip()
    if not t:
        raise ValueError("Step 5 system instructions are empty; nothing to save.")
    _STEP5_OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    _STEP5_OVERRIDE.write_text(t + "\n", encoding="utf-8")


def clear_step5_base_instructions_override() -> None:
    try:
        _STEP5_OVERRIDE.unlink()
    except OSError:
        pass


def load_step5_system_prompt(*, instructions_base: str | None = None) -> str:
    """
    Full system message for Step 5 Chat Completions.
    If ``instructions_base`` is set, it replaces disk/doc. There is no separate appended block.
    """
    if instructions_base is not None:
        s = instructions_base.strip()
        if not s:
            raise ValueError(
                "Step 5 system instructions are empty. "
                "Edit the Step 5 panel or reset to the built-in doc."
            )
        return s
    return load_step5_base_instructions()


def system_prompt_sha256(prompt_text: str) -> str:
    h = hashlib.sha256()
    h.update(prompt_text.encode("utf-8"))
    return h.hexdigest()


def _fetch_root_entries(
    conn,
    *,
    root_arabic: str | None,
    root_buckwalter: str | None,
) -> tuple[int, list[Step5LexiconEntry]]:
    ar = (root_arabic or "").strip()
    if not ar and root_buckwalter:
        ar = (buckwalter_root_to_arabic(root_buckwalter) or "").strip()
    if not ar:
        return (0, [])
    rw_norm = normalize_arabic(ar)
    if not rw_norm:
        return (0, [])
    rr = conn.execute(
        "SELECT id FROM lexicon_roots WHERE root_word_normalized = ?",
        (rw_norm,),
    ).fetchone()
    if rr is None:
        return (0, [])
    root_id = int(rr["id"])
    rows = conn.execute(
        """
        SELECT id, seq, COALESCE(NULLIF(TRIM(heading_normalized), ''), heading_raw) AS heading, definition
        FROM lexicon_entries
        WHERE root_id = ?
        ORDER BY seq ASC, id ASC
        """,
        (root_id,),
    ).fetchall()
    entries = [
        Step5LexiconEntry(
            id=int(r["id"]),
            seq=int(r["seq"]),
            heading=str(r["heading"] or ""),
            definition=str(r["definition"] or ""),
        )
        for r in rows
    ]
    return (root_id, entries)


def build_verse_manifest(conn, *, find_match_id: int) -> Step5Manifest:
    token_ids = fetch_token_ids_for_find_match(conn, int(find_match_id))
    if not token_ids:
        return Step5Manifest(units=(), total_combos=0)
    words = fetch_morpheme_roots_for_token_ids(conn, token_ids)
    units: list[Step5Unit] = []
    for w in words:
        for m in w.morphemes:
            root_id, entries = _fetch_root_entries(
                conn,
                root_arabic=m.root_arabic,
                root_buckwalter=m.root_buckwalter,
            )
            if root_id <= 0 or not entries:
                continue
            units.append(
                Step5Unit(
                    word_no=int(w.word_no),
                    kalimah_seq=int(m.kalimah_seq),
                    token_uthmani=str(w.token_uthmani or ""),
                    morpheme_surface=str(m.surface or ""),
                    pos=str(m.pos) if m.pos else None,
                    root_arabic=str(m.root_arabic) if m.root_arabic else None,
                    root_buckwalter=(
                        str(m.root_buckwalter) if m.root_buckwalter else None
                    ),
                    root_id=root_id,
                    entries=tuple(entries),
                )
            )
    units.sort(key=lambda x: (x.word_no, x.kalimah_seq, x.root_id))
    if not units:
        return Step5Manifest(units=tuple(units), total_combos=0)
    counts = [len(u.entries) for u in units]
    total = _safe_total_combos(counts)
    return Step5Manifest(units=tuple(units), total_combos=total)


def format_lane_meanings_from_manifest(manifest: Step5Manifest) -> str:
    """
    All Lane lexicon entry headings/definitions linked to the verse via morpheme roots,
    deduped by entry id, for CrossEncoder passage text (Step 5 shortlist).
    """
    by_id: dict[int, Step5LexiconEntry] = {}
    for u in manifest.units:
        for e in u.entries:
            by_id[e.id] = e
    if not by_id:
        return ""
    ordered = sorted(by_id.values(), key=lambda e: (e.seq, e.id))
    parts: list[str] = []
    for e in ordered:
        h = (e.heading or "").strip()
        d = (e.definition or "").strip()
        if h and d:
            parts.append(f"{h}: {d}")
        elif d:
            parts.append(d)
        elif h:
            parts.append(h)
    if not parts:
        return ""
    return "Lane meanings:\n" + "\n\n".join(parts)


def manifest_to_json(manifest: Step5Manifest) -> str:
    arr: list[dict[str, object]] = []
    for u in manifest.units:
        arr.append(
            {
                "word_no": u.word_no,
                "kalimah_seq": u.kalimah_seq,
                "token_uthmani": u.token_uthmani,
                "morpheme_surface": u.morpheme_surface,
                "pos": u.pos,
                "root_arabic": u.root_arabic,
                "root_buckwalter": u.root_buckwalter,
                "root_id": u.root_id,
                "entries": [
                    {
                        "id": e.id,
                        "seq": e.seq,
                        "heading": e.heading,
                        "definition": e.definition,
                    }
                    for e in u.entries
                ],
            }
        )
    return json.dumps(arr, ensure_ascii=False)


def manifest_from_json(raw: str) -> Step5Manifest:
    obj = json.loads(raw)
    if not isinstance(obj, list):
        return Step5Manifest(units=(), total_combos=0)
    units: list[Step5Unit] = []
    for x in obj:
        if not isinstance(x, dict):
            continue
        entries_obj = x.get("entries")
        entries: list[Step5LexiconEntry] = []
        if isinstance(entries_obj, list):
            for e in entries_obj:
                if not isinstance(e, dict):
                    continue
                try:
                    entries.append(
                        Step5LexiconEntry(
                            id=int(e.get("id")),
                            seq=int(e.get("seq")),
                            heading=str(e.get("heading") or ""),
                            definition=str(e.get("definition") or ""),
                        )
                    )
                except (TypeError, ValueError):
                    continue
        if not entries:
            continue
        try:
            units.append(
                Step5Unit(
                    word_no=int(x.get("word_no")),
                    kalimah_seq=int(x.get("kalimah_seq")),
                    token_uthmani=str(x.get("token_uthmani") or ""),
                    morpheme_surface=str(x.get("morpheme_surface") or ""),
                    pos=str(x.get("pos")) if x.get("pos") else None,
                    root_arabic=str(x.get("root_arabic")) if x.get("root_arabic") else None,
                    root_buckwalter=(
                        str(x.get("root_buckwalter"))
                        if x.get("root_buckwalter")
                        else None
                    ),
                    root_id=int(x.get("root_id")),
                    entries=tuple(entries),
                )
            )
        except (TypeError, ValueError):
            continue
    if not units:
        return Step5Manifest(units=tuple(units), total_combos=0)
    counts = [len(u.entries) for u in units]
    total = _safe_total_combos(counts)
    return Step5Manifest(units=tuple(units), total_combos=total)


def ordinal_to_combo(ordinal: int, entry_counts: list[int]) -> tuple[int, ...]:
    if ordinal < 0:
        raise ValueError("ordinal must be >= 0")
    if not entry_counts:
        return ()
    combo_rev: list[int] = []
    rem = int(ordinal)
    for base in reversed(entry_counts):
        b = max(1, int(base))
        combo_rev.append((rem % b) + 1)  # one-based entry index
        rem //= b
    return tuple(reversed(combo_rev))


def combo_to_json(manifest: Step5Manifest, combo: tuple[int, ...]) -> str:
    arr: list[dict[str, int]] = []
    for i, pick in enumerate(combo):
        u = manifest.units[i]
        arr.append(
            {
                "word_no": int(u.word_no),
                "kalimah_seq": int(u.kalimah_seq),
                "entry_pick": int(pick),
            }
        )
    return json.dumps(arr, ensure_ascii=False)


LOADED_ALL_ENTRIES_COMBO_JSON = json.dumps([{"all_entries": True}], ensure_ascii=False)


def is_loaded_all_entries_combo_json(raw: str | None) -> bool:
    try:
        obj = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return False
    if not isinstance(obj, list) or len(obj) != 1:
        return False
    x = obj[0]
    return isinstance(x, dict) and x.get("all_entries") is True


def _root_letters(root_text: str | None) -> list[str]:
    rw = normalize_arabic(root_text or "")
    return [ch for ch in rw if ch.strip()]


def build_payload(
    *,
    question: str,
    topic: str,
    connotation: str,
    verse_arabic: str,
    manifest: Step5Manifest,
    combo: tuple[int, ...],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    root_words: list[dict[str, object]] = []
    context_rows: list[dict[str, object]] = []
    for i, pick in enumerate(combo):
        u = manifest.units[i]
        idx = max(1, int(pick)) - 1
        if idx >= len(u.entries):
            idx = len(u.entries) - 1
        entry = u.entries[idx]
        definition_excerpt = entry.definition.strip().replace("\n", " ")
        if len(definition_excerpt) > 900:
            definition_excerpt = definition_excerpt[:900] + "..."
        meaning_line = (
            f"{entry.heading}: {definition_excerpt}"
            if entry.heading
            else definition_excerpt
        )
        root_words.append(
            {
                "position": int(u.word_no),
                "roots": _root_letters(u.root_arabic or u.root_buckwalter),
                "arabic_word": u.morpheme_surface or u.token_uthmani,
                "grammar": u.pos or "",
                "relevance_index": 5,
                "meanings": [meaning_line],
            }
        )
        context_rows.append(
            {
                "word_no": u.word_no,
                "kalimah_seq": u.kalimah_seq,
                "token_uthmani": u.token_uthmani,
                "morpheme_surface": u.morpheme_surface,
                "lexicon_entry_id": entry.id,
                "entry_seq": entry.seq,
                "entry_heading": entry.heading,
                "entry_definition_excerpt": definition_excerpt,
            }
        )
    payload: dict[str, object] = {
        "question": (question or "").strip(),
        "topic": (topic or "").strip(),
        "connotation": (connotation or "").strip(),
        "verse_arabic": (verse_arabic or "").strip(),
        "root_words": root_words,
    }
    return payload, context_rows


def build_payload_all_entries(
    *,
    question: str,
    topic: str,
    connotation: str,
    verse_arabic: str,
    manifest: Step5Manifest,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """One LLM request per verse: every Lane entry for each morpheme unit in ``meanings``."""
    root_words: list[dict[str, object]] = []
    context_rows: list[dict[str, object]] = []
    for u in manifest.units:
        meaning_lines: list[str] = []
        for entry in u.entries:
            definition_excerpt = entry.definition.strip().replace("\n", " ")
            if len(definition_excerpt) > 900:
                definition_excerpt = definition_excerpt[:900] + "..."
            meaning_line = (
                f"{entry.heading}: {definition_excerpt}"
                if entry.heading
                else definition_excerpt
            )
            meaning_lines.append(meaning_line)
            context_rows.append(
                {
                    "word_no": u.word_no,
                    "kalimah_seq": u.kalimah_seq,
                    "token_uthmani": u.token_uthmani,
                    "morpheme_surface": u.morpheme_surface,
                    "lexicon_entry_id": entry.id,
                    "entry_seq": entry.seq,
                    "entry_heading": entry.heading,
                    "entry_definition_excerpt": definition_excerpt,
                }
            )
        root_words.append(
            {
                "position": int(u.word_no),
                "roots": _root_letters(u.root_arabic or u.root_buckwalter),
                "arabic_word": u.morpheme_surface or u.token_uthmani,
                "grammar": u.pos or "",
                "relevance_index": 5,
                "meanings": meaning_lines,
            }
        )
    payload: dict[str, object] = {
        "question": (question or "").strip(),
        "topic": (topic or "").strip(),
        "connotation": (connotation or "").strip(),
        "verse_arabic": (verse_arabic or "").strip(),
        "root_words": root_words,
    }
    return payload, context_rows


def truncate_payload_for_tokens(payload: dict[str, object], max_input_tokens: int) -> dict[str, object]:
    """
    Keep payload inside a rough token budget.

    We use a simple 4 chars/token heuristic and shorten meaning text first.
    """
    budget = max(256, int(max_input_tokens))
    out = json.loads(json.dumps(payload, ensure_ascii=False))
    while len(json.dumps(out, ensure_ascii=False)) // 4 > budget:
        words = out.get("root_words")
        if not isinstance(words, list) or not words:
            break
        longest_i = -1
        longest_j = -1
        longest_len = -1
        for i, w in enumerate(words):
            if not isinstance(w, dict):
                continue
            meanings = w.get("meanings")
            if not isinstance(meanings, list) or not meanings:
                continue
            for j, line in enumerate(meanings):
                s = str(line)
                if len(s) > longest_len:
                    longest_len = len(s)
                    longest_i = i
                    longest_j = j
        if longest_i < 0 or longest_len <= 80:
            words.pop()  # hard fallback: drop trailing unit
            continue
        w = words[longest_i]
        meanings = w.get("meanings")
        if isinstance(meanings, list) and meanings and longest_j >= 0:
            s = str(meanings[longest_j])
            cut = max(80, int(len(s) * 0.75))
            meanings[longest_j] = s[:cut].rstrip() + "..."
    return out


def parse_step5_response_json(raw_text: str) -> dict[str, object] | None:
    txt = (raw_text or "").strip()
    if not txt:
        return None
    for candidate in (
        txt,
        txt.removeprefix("```json").removeprefix("```").removesuffix("```").strip(),
    ):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        return obj
    return None


def system_prompt_path() -> Path:
    return _DOC
