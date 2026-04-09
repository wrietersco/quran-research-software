"""Run heuristic token→root mapping and apply manual overrides."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_db_path  # noqa: E402
from src.db.connection import connect  # noqa: E402
from src.mapping.root_mapper import apply_overrides, run_heuristic_mapping  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Max tokens to process")
    ap.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not delete existing heuristic analyses before re-run",
    )
    ap.add_argument(
        "--min-confidence",
        type=float,
        default=0.35,
        help="Minimum score to keep a candidate",
    )
    ap.add_argument(
        "--skip-heuristic",
        action="store_true",
        help="Only apply overrides from token_root_overrides",
    )
    args = ap.parse_args()

    conn = connect(get_db_path())
    try:
        if not args.skip_heuristic:
            n = run_heuristic_mapping(
                conn,
                clear_existing=not args.no_clear,
                limit=args.limit,
                min_confidence=args.min_confidence,
            )
            conn.commit()
            print(f"Heuristic mapping processed {n} tokens.")
        o = apply_overrides(conn)
        conn.commit()
        print(f"Applied {o} manual overrides.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
