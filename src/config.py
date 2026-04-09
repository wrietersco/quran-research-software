"""Central configuration (paths, defaults)."""

from __future__ import annotations

import os
from pathlib import Path

# Project root = parent of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load OPENAI_API_KEY and other vars from project-root .env when present."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_file, override=False)


_load_dotenv()

# Default SQLite database (plan: data/db/quran_lexicon.db)
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "db" / "quran_lexicon.db"

# Raw data directories
RAW_LEXICON_DIR = PROJECT_ROOT / "data" / "raw" / "lexicon"
RAW_QURAN_DIR = PROJECT_ROOT / "data" / "raw" / "quran"

# Full-mushaf JSON (verse objects: chapter, verse, text) used by find_verses fallback and DB import
QURAN_ROOT_JSON = PROJECT_ROOT / "quran.json"


def get_db_path() -> Path:
    p = os.environ.get("QURAN_LEXICON_DB")
    if p:
        return Path(p).expanduser().resolve()
    return DEFAULT_DB_PATH.resolve()
