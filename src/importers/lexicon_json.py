"""Import Lane-style lexicon JSON into SQLite."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..config import PROJECT_ROOT, RAW_LEXICON_DIR
from ..db.repositories import (
    insert_lexicon_entry,
    replace_entries_for_root,
    upsert_lexicon_root,
)
from ..normalize.arabic import canonical_heading, normalize_arabic


def discover_lexicon_json_files(extra_dirs: list[Path] | None = None) -> list[Path]:
    """
    Find lane_lexicon*.json files.

    If data/raw/lexicon contains any matches, only that directory is used (avoids
    duplicate imports when the same files also exist in project root). Otherwise
    falls back to project root. extra_dirs are always included.
    """
    dirs: list[Path] = []
    if RAW_LEXICON_DIR.exists() and list(RAW_LEXICON_DIR.glob("lane_lexicon*.json")):
        dirs.append(RAW_LEXICON_DIR)
    else:
        dirs.append(PROJECT_ROOT)
    if extra_dirs:
        dirs.extend(extra_dirs)
    seen_names: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("lane_lexicon*.json")):
            name = p.name
            if name in seen_names:
                continue
            seen_names.add(name)
            out.append(p)
    return sorted(out, key=lambda x: x.name)


def import_lexicon_json_file(
    conn: sqlite3.Connection,
    path: Path,
    *,
    replace_existing_entries: bool = False,
) -> tuple[int, int]:
    """
    Import one JSON file (array of {root word, main entries}).

    If a root already exists and replace_existing_entries is False, the root is skipped
    (idempotent re-import). If replace_existing_entries is True, existing entries for
    that root are replaced.

    Returns (roots_written, entries_inserted, roots_skipped_existing).

    ``roots_skipped_existing`` counts roots not re-imported because they already existed
    and ``replace_existing_entries`` is False (idempotent default).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array in {path}")

    roots_written = 0
    entries_inserted = 0
    roots_skipped_existing = 0
    source_ref = str(path)

    for obj in data:
        root_word = obj.get("root word") or obj.get("root_word")
        if root_word is None:
            continue
        main_entries = obj.get("main entries") or obj.get("main_entries") or []
        rw_norm = normalize_arabic(str(root_word))

        cur = conn.execute(
            "SELECT id FROM lexicon_roots WHERE root_word_normalized = ?",
            (rw_norm,),
        ).fetchone()

        if cur and not replace_existing_entries:
            roots_skipped_existing += 1
            continue

        root_id = upsert_lexicon_root(
            conn,
            str(root_word),
            rw_norm,
            source_ref=source_ref,
        )
        if cur:
            replace_entries_for_root(conn, root_id)

        for seq, entry_obj in enumerate(main_entries, start=1):
            if not isinstance(entry_obj, dict) or len(entry_obj) != 1:
                continue
            heading_raw, definition = next(iter(entry_obj.items()))
            heading_raw = str(heading_raw)
            definition = str(definition)
            heading_norm = canonical_heading(seq, heading_raw)
            insert_lexicon_entry(
                conn,
                root_id,
                seq,
                heading_raw,
                heading_norm,
                definition,
            )
            entries_inserted += 1

        roots_written += 1

    return roots_written, entries_inserted, roots_skipped_existing
