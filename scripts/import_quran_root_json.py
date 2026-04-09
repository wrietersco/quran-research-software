"""Import project-root quran.json into quran_verses and quran_tokens (no lexicon/mapping)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import QURAN_ROOT_JSON, get_db_path  # noqa: E402
from src.db.connection import connect, init_db  # noqa: E402
from src.importers.quran_root_json import import_quran_root_json  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Import mushaf-style quran.json (verse objects) into SQLite."
    )
    ap.add_argument(
        "json_path",
        type=str,
        nargs="?",
        default=None,
        help=f"JSON file (default: {QURAN_ROOT_JSON})",
    )
    args = ap.parse_args()
    path = Path(args.json_path) if args.json_path else QURAN_ROOT_JSON
    if not path.is_file():
        print(f"File not found: {path}")
        sys.exit(1)

    db_path = get_db_path()
    init_db(db_path)
    conn = connect(db_path)
    try:
        st = import_quran_root_json(conn, path, source_ref=path.name)
        conn.commit()
        print(
            f"Imported {st.verses_upserted} verse(s), {st.tokens_upserted} token row(s) "
            f"from {path.name}."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
