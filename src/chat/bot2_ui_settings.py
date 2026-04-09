"""Persist Bot 2 UI: model, optional vector stores, max synonyms, optional temperature."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.chat.openai_documented_models import remap_removed_doc_model
from src.config import PROJECT_ROOT

_SETTINGS_PATH = PROJECT_ROOT / "data" / "chat" / "bot2_ui_settings.json"


@dataclass
class Bot2UiSettings:
    model: str = ""
    vector_store_ids: list[str] = field(default_factory=list)
    max_synonyms: int = 8
    temperature: float | None = None  # None → engine default BOT2_TEMPERATURE_DEFAULT
    skip_existing_bot2: bool = False  # skip connotations that already have synonyms for current Bot 1 run


def _clamp_max_synonyms(n: int) -> int:
    if n < 1:
        return 1
    if n > 30:
        return 30
    return n


def load_bot2_ui_settings() -> Bot2UiSettings:
    try:
        raw = _SETTINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return Bot2UiSettings()
    if not isinstance(data, dict):
        return Bot2UiSettings()
    model = data.get("model")
    raw_m = model.strip() if isinstance(model, str) else ""
    mstr = remap_removed_doc_model(raw_m)
    vs = data.get("vector_store_ids")
    ids: list[str] = []
    if isinstance(vs, list):
        ids = [str(x).strip() for x in vs if str(x).strip()]
    mx = data.get("max_synonyms")
    try:
        max_syn = _clamp_max_synonyms(int(mx)) if mx is not None else 8
    except (TypeError, ValueError):
        max_syn = 8
    temp_raw = data.get("temperature")
    temp: float | None = None
    if temp_raw is not None:
        try:
            temp = float(temp_raw)
        except (TypeError, ValueError):
            temp = None
    skip_ex = bool(data.get("skip_existing_bot2", False))
    out = Bot2UiSettings(
        model=mstr,
        vector_store_ids=ids,
        max_synonyms=max_syn,
        temperature=temp,
        skip_existing_bot2=skip_ex,
    )
    if mstr != raw_m:
        save_bot2_ui_settings(out)
    return out


def save_bot2_ui_settings(settings: Bot2UiSettings) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "model": settings.model.strip(),
        "vector_store_ids": list(settings.vector_store_ids),
        "max_synonyms": _clamp_max_synonyms(int(settings.max_synonyms)),
        "temperature": settings.temperature,
        "skip_existing_bot2": bool(settings.skip_existing_bot2),
    }
    _SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_bot2_ui_model() -> str:
    return load_bot2_ui_settings().model


def save_bot2_ui_model(model: str) -> None:
    s = load_bot2_ui_settings()
    s.model = model
    save_bot2_ui_settings(s)
