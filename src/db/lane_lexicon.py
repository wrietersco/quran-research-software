"""Load Lane lexicon roots + entries from SQLite for the Lanes Lexicon browser tab."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class LaneLexiconEntryRow:
    entry_id: int
    root_id: int
    seq: int
    heading_raw: str
    definition: str
    word_count: int


@dataclass(frozen=True)
class LaneLexiconRootGroup:
    root_id: int
    root_word: str
    entries: tuple[LaneLexiconEntryRow, ...]


def description_word_count(text: str) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    return len(t.split())


def fetch_lane_lexicon_groups(conn: sqlite3.Connection) -> list[LaneLexiconRootGroup]:
    cur = conn.execute(
        """
        SELECT r.id, r.root_word, e.id, e.seq, e.heading_raw, e.definition
        FROM lexicon_roots r
        JOIN lexicon_entries e ON e.root_id = r.id
        ORDER BY r.root_word_normalized COLLATE NOCASE, e.seq
        """
    )
    by_root: dict[int, list[tuple[int, int, str, str, int]]] = defaultdict(list)
    root_words: dict[int, str] = {}
    for rid, rw, eid, seq, hr, df in cur.fetchall():
        root_words[rid] = str(rw)
        d = str(df) if df is not None else ""
        wc = description_word_count(d)
        by_root[rid].append((int(eid), int(seq), str(hr), d, wc))

    groups: list[LaneLexiconRootGroup] = []
    for rid in sorted(by_root.keys(), key=lambda i: (root_words[i].lower(), i)):
        ents = tuple(
            LaneLexiconEntryRow(eid, rid, seq, hr, df, wc)
            for eid, seq, hr, df, wc in by_root[rid]
        )
        groups.append(LaneLexiconRootGroup(rid, root_words[rid], ents))
    return groups
