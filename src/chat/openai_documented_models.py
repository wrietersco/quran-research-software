"""Curated OpenAI model aliases for UI dropdowns (Bots 1 & 2).

Each id is a non-deprecated **alias** from an official model page under
https://platform.openai.com/docs/models/ where the model lists the Responses
API and **function calling** supported (required for our tool-calling bots).

Omitted by design:
- Deprecated snapshots such as ``o1-preview`` (marked deprecated on the o1 page).
- Models shut down per https://platform.openai.com/docs/deprecations (e.g. ``o1-mini``).
- Models documented without function calling (e.g. ``o4-mini-deep-research``).

Refresh this module when OpenAI's catalog changes.
"""

from __future__ import annotations

# IDs shut down or deprecated as replacements exist; values are documented aliases.
_REMOVED_MODEL_REPLACEMENTS: dict[str, str] = {
    "o1-mini": "o4-mini",
    "o1-preview": "o3",
}

# Newest / recommended first for combobox UX.
RESPONSES_TOOL_MODEL_CHOICES: tuple[str, ...] = (
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "o4-mini",
    "o3-pro",
    "o3",
    "o3-mini",
    "o1-pro",
    "o1",
)


def remap_removed_doc_model(model: str) -> str:
    """Map removed/deprecated API model ids to current documented replacements."""
    m = (model or "").strip()
    return _REMOVED_MODEL_REPLACEMENTS.get(m, m)
