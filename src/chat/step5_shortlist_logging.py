"""File logging for Step 5 SHORTLIST (CrossEncoder + LLM)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from src.config import PROJECT_ROOT

LOGGER_NAME = "step5_shortlist"
_LOG_DIR = PROJECT_ROOT / "data" / "chat" / "logs"
_LOG_FILE = _LOG_DIR / "step5_shortlist.log"
_configured = False


def shortlist_log_file_path() -> str:
    return str(_LOG_FILE)


def get_step5_shortlist_logger() -> logging.Logger:
    """Return the SHORTLIST logger; attach a rotating file handler once per process."""
    global _configured
    log = logging.getLogger(LOGGER_NAME)
    if not _configured:
        _configured = True
        log.setLevel(logging.DEBUG)
        log.propagate = False
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        log.addHandler(fh)
    return log
