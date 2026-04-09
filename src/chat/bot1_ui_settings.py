"""Persist Bot 1 UI: model id and optional vector store IDs for file_search."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.chat.openai_documented_models import remap_removed_doc_model
from src.config import PROJECT_ROOT

_SETTINGS_PATH = PROJECT_ROOT / "data" / "chat" / "bot1_ui_settings.json"


@dataclass
class Bot1UiSettings:
    model: str = ""
    vector_store_ids: list[str] = field(default_factory=list)
    temperature: float | None = None  # None → engine BOT1_TEMPERATURE


def load_bot1_ui_settings() -> Bot1UiSettings:
    try:
        raw = _SETTINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return Bot1UiSettings()
    if not isinstance(data, dict):
        return Bot1UiSettings()
    model = data.get("model")
    mstr = remap_removed_doc_model(model.strip() if isinstance(model, str) else "")
    vs = data.get("vector_store_ids")
    ids: list[str] = []
    if isinstance(vs, list):
        ids = [str(x).strip() for x in vs if str(x).strip()]
    temp_raw = data.get("temperature")
    temp: float | None = None
    if temp_raw is not None:
        try:
            temp = float(temp_raw)
        except (TypeError, ValueError):
            temp = None
    out = Bot1UiSettings(model=mstr, vector_store_ids=ids, temperature=temp)
    raw_m = model.strip() if isinstance(model, str) else ""
    if mstr != raw_m:
        save_bot1_ui_settings(out)
    return out


def save_bot1_ui_settings(settings: Bot1UiSettings) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": settings.model.strip(),
        "vector_store_ids": list(settings.vector_store_ids),
        "temperature": settings.temperature,
    }
    _SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_bot1_ui_model() -> str:
    return load_bot1_ui_settings().model


def save_bot1_ui_model(model: str) -> None:
    s = load_bot1_ui_settings()
    s.model = model
    save_bot1_ui_settings(s)
