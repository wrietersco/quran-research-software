"""Run sanity checks and EXPLAIN on hot queries."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_db_path  # noqa: E402
from src.db.connection import connect  # noqa: E402


def main() -> None:
    conn = connect(get_db_path())
    try:
        checks = [
            "SELECT COUNT(*) AS c FROM lexicon_roots",
            "SELECT COUNT(*) AS c FROM lexicon_entries",
            "SELECT COUNT(*) AS c FROM quran_tokens",
            "SELECT COUNT(*) AS c FROM token_root_analysis WHERE is_primary = 1",
        ]
        for sql in checks:
            row = conn.execute(sql).fetchone()
            print(f"{sql} -> {dict(row)}")

        explain_sql = """
        EXPLAIN QUERY PLAN
        SELECT t.surah_no, t.ayah_no, t.word_no, r.root_word
        FROM quran_tokens t
        JOIN token_root_analysis a ON a.token_id = t.id AND a.is_primary = 1
        JOIN lexicon_roots r ON r.id = a.root_id
        WHERE r.root_word_normalized = ?
        LIMIT 20
        """
        for r in conn.execute(explain_sql, ("علم",)):
            print(dict(r))

        fts = "SELECT COUNT(*) FROM lexicon_entries_fts WHERE lexicon_entries_fts MATCH 'God'"
        try:
            c = conn.execute(fts).fetchone()[0]
            print(f"FTS sample match count: {c}")
        except Exception as e:
            print(f"FTS sample skipped: {e}")
    finally:
        conn.close()
    print(f"DB: {get_db_path()}")


if __name__ == "__main__":
    main()
