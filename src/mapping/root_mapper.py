"""Heuristic Quran token → lexicon root mapping (v1)."""

from __future__ import annotations

import sqlite3
from typing import Sequence

from ..db.repositories import (
    delete_analyses_for_token,
    fetch_all_roots_normalized,
    insert_token_root_analysis,
)
from ..normalize.arabic import normalize_arabic, strip_clitics_prefix

SOURCE_HEURISTIC = "heuristic_v1"
SOURCE_OVERRIDE = "manual_override"


def _score_match(token_norm: str, stripped: str, root_norm: str) -> float:
    """Higher is better; 0 means no match."""
    if not root_norm:
        return 0.0
    # Exact match on full token
    if token_norm == root_norm:
        return 1.0
    if stripped == root_norm:
        return 0.95
    # Root as contiguous substring (morphological hint; noisy)
    if root_norm in stripped:
        return 0.5 + 0.4 * (len(root_norm) / max(len(stripped), 1))
    if root_norm in token_norm:
        return 0.4 + 0.3 * (len(root_norm) / max(len(token_norm), 1))
    # Prefix alignment
    if stripped.startswith(root_norm):
        return 0.45 + 0.35 * (len(root_norm) / max(len(stripped), 1))
    return 0.0


def run_heuristic_mapping(
    conn: sqlite3.Connection,
    *,
    clear_existing: bool = True,
    limit: int | None = None,
    min_confidence: float = 0.35,
    max_candidates: int = 5,
) -> int:
    """
    For each quran_token, insert candidate token_root_analysis rows.

    Uses normalized substring / prefix heuristics (not full morphology).
    Returns number of tokens processed.
    """
    roots = fetch_all_roots_normalized(conn)
    if not roots:
        return 0

    q = "SELECT id, token_plain FROM quran_tokens ORDER BY surah_no, ayah_no, word_no"
    params: list[object] = []
    if limit is not None:
        q += " LIMIT ?"
        params.append(int(limit))
    tokens = conn.execute(q, params).fetchall()

    processed = 0
    for row in tokens:
        token_id = int(row["id"])
        token_plain = str(row["token_plain"])
        if clear_existing:
            delete_analyses_for_token(conn, token_id)

        n = normalize_arabic(token_plain)
        stripped = strip_clitics_prefix(n)

        scored: list[tuple[float, int, str, str]] = []
        for rid, _rw, rnorm in roots:
            sc = _score_match(n, stripped, rnorm)
            if sc >= min_confidence:
                scored.append((sc, rid, _rw, rnorm))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:max_candidates]

        if not top:
            processed += 1
            continue

        for i, (sc, rid, _rw, _rnorm) in enumerate(top):
            insert_token_root_analysis(
                conn,
                token_id,
                rid,
                lemma=None,
                pattern=None,
                source=SOURCE_HEURISTIC,
                confidence=float(sc),
                is_primary=(i == 0),
                notes=None,
            )
        processed += 1

    return processed


def apply_overrides(conn: sqlite3.Connection) -> int:
    """
    For rows in token_root_overrides, set primary analysis to the chosen root.

    Clears is_primary on other analyses for that token and inserts/updates override row.
    Returns number of overrides applied.
    """
    rows = conn.execute("SELECT token_id, root_id, reason FROM token_root_overrides").fetchall()
    n = 0
    for row in rows:
        token_id = int(row["token_id"])
        root_id = int(row["root_id"])
        reason = row["reason"]
        conn.execute(
            "UPDATE token_root_analysis SET is_primary = 0 WHERE token_id = ?",
            (token_id,),
        )
        insert_token_root_analysis(
            conn,
            token_id,
            root_id,
            lemma=None,
            pattern=None,
            source=SOURCE_OVERRIDE,
            confidence=1.0,
            is_primary=True,
            notes=reason,
        )
        n += 1
    return n
