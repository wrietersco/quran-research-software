"""Lightweight OpenAI API connectivity check (auth + reachability)."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Ensure .env is loaded when this module is imported before src.config elsewhere.
import src.config  # noqa: F401  — side effect: load_dotenv


@dataclass(frozen=True)
class OpenAiHealthResult:
    ok: bool
    """True if a minimal authenticated API call succeeded."""
    summary: str
    """Short single-line message for status labels."""
    detail: str | None = None
    """Longer error text or None on success."""


def _format_api_error(exc: BaseException) -> str:
    s = str(exc).strip()
    if len(s) > 500:
        return s[:497] + "..."
    return s


def check_openai_api_health() -> OpenAiHealthResult:
    """
    Perform a small, low-cost request: list models (validates API key and scopes).
    Uses the same env vars as the refiner: OPENAI_API_KEY, optional OPENAI_BASE_URL.
    """
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return OpenAiHealthResult(
            ok=False,
            summary="No API key",
            detail="Set OPENAI_API_KEY in .env or the environment, then restart.",
        )

    try:
        from openai import OpenAI
    except ImportError:
        return OpenAiHealthResult(
            ok=False,
            summary="SDK missing",
            detail="Install the OpenAI SDK: pip install openai",
        )

    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    try:
        client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
        # One authenticated GET; avoids chat token charges.
        client.models.list()
    except Exception as e:
        return OpenAiHealthResult(
            ok=False,
            summary="Not OK",
            detail=_format_api_error(e),
        )

    return OpenAiHealthResult(ok=True, summary="OK", detail=None)
