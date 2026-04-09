"""Create or upgrade SQLite schema at data/db/quran_lexicon.db."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_db_path  # noqa: E402
from src.db.connection import init_db  # noqa: E402


def main() -> None:
    p = get_db_path()
    init_db(p)
    print(f"Initialized database: {p}")


if __name__ == "__main__":
    main()
