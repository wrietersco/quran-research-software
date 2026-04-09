"""Import Quran word JSON into quran_tokens."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_db_path  # noqa: E402
from src.db.connection import connect  # noqa: E402
from src.importers.quran_json import import_quran_words_json  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", type=str, help="Path to quran words JSON file")
    args = ap.parse_args()
    path = Path(args.json_path)
    if not path.is_file():
        print(f"File not found: {path}")
        sys.exit(1)

    conn = connect(get_db_path())
    try:
        n = import_quran_words_json(conn, path)
        conn.commit()
        print(f"Imported {n} tokens into quran_tokens.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
