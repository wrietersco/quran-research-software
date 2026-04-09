"""Import lane_lexicon*.json files into SQLite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_db_path  # noqa: E402
from src.db.connection import connect  # noqa: E402
from src.db.repositories import truncate_lexicon_tables  # noqa: E402
from src.importers.lexicon_json import (  # noqa: E402
    discover_lexicon_json_files,
    import_lexicon_json_file,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--replace-entries",
        action="store_true",
        help="Replace lexicon entry rows for roots that already exist",
    )
    ap.add_argument(
        "--truncate",
        action="store_true",
        help="Delete all lexicon data before import",
    )
    ap.add_argument(
        "files",
        nargs="*",
        type=str,
        help="Optional explicit JSON paths (default: discover lane_lexicon*.json)",
    )
    args = ap.parse_args()

    db_path = get_db_path()
    paths = [Path(f) for f in args.files] if args.files else discover_lexicon_json_files()
    if not paths:
        print("No lane_lexicon*.json files found. Place files under data/raw/lexicon/ or project root.")
        sys.exit(1)

    conn = connect(db_path)
    try:
        if args.truncate:
            truncate_lexicon_tables(conn)
            conn.commit()
            print("Truncated lexicon tables.")

        total_roots = 0
        total_entries = 0
        total_skipped = 0
        for path in paths:
            r, e, skipped = import_lexicon_json_file(
                conn,
                path,
                replace_existing_entries=args.replace_entries,
            )
            conn.commit()
            total_roots += r
            total_entries += e
            total_skipped += skipped
            print(
                f"{path.name}: roots_written={r}, entries_inserted={e}, "
                f"roots_skipped_already_in_db={skipped}"
            )

        print(
            f"Done. Total roots_written={total_roots}, entries_inserted={total_entries}, "
            f"roots_skipped_already_in_db={total_skipped}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
