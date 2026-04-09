"""Quick health check: row counts for main tables."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_db_path  # noqa: E402
from src.db.connection import connect  # noqa: E402


def main() -> None:
    p = get_db_path()
    print(f"Database path: {p}")
    print(f"File exists: {p.is_file()}")
    if not p.is_file():
        print("No database file - run: python database.py")
        return

    conn = connect(p)
    try:
        rows = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        print(f"User tables ({len(rows)}):", ", ".join(r[0] for r in rows))

        checks = [
            "lexicon_roots",
            "lexicon_entries",
            "quran_tokens",
            "token_root_analysis",
        ]
        for t in checks:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n:,}")

        try:
            n_fts = conn.execute("SELECT COUNT(*) FROM lexicon_entries_fts").fetchone()[0]
            print(f"  lexicon_entries_fts (FTS index rows): {n_fts:,}")
        except Exception as e:
            print(f"  lexicon_entries_fts: ({e})")

        prim = conn.execute(
            "SELECT COUNT(*) FROM token_root_analysis WHERE is_primary = 1"
        ).fetchone()[0]
        print(f"  Primary token-to-root mappings: {prim:,}")

        # Expectations (rough)
        lr = conn.execute("SELECT COUNT(*) FROM lexicon_roots").fetchone()[0]
        le = conn.execute("SELECT COUNT(*) FROM lexicon_entries").fetchone()[0]
        qt = conn.execute("SELECT COUNT(*) FROM quran_tokens").fetchone()[0]

        print("\nAssessment:")
        if lr > 0 and le > 0:
            print("  Lexicon: OK - roots and entries present.")
        elif lr == 0 and le == 0:
            print("  Lexicon: EMPTY - import lane_lexicon*.json (e.g. python database.py --truncate-lexicon).")
        else:
            print("  Lexicon: PARTIAL - unexpected root/entry mismatch.")

        if qt == 0:
            print("  Quran tokens: EMPTY - add JSON under data/raw/quran/ or use --quran-file.")
        elif qt < 100:
            print(f"  Quran tokens: {qt} rows (sample/small file only; full Quran is ~77k+ words depending on source).")
        else:
            print(f"  Quran tokens: {qt:,} rows present.")

        if qt > 0 and prim == 0:
            print("  Mapping: no primary analyses - run: python database.py (with mapping) or scripts/map_roots.py")
        elif qt > 0:
            print(f"  Mapping: {prim:,} primary links (heuristic/override).")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
