"""Persist Step 5 UI settings."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.config import PROJECT_ROOT

_SETTINGS_PATH = PROJECT_ROOT / "data" / "chat" / "step5_ui_settings.json"


@dataclass
class Step5UiSettings:
    provider: str = "openai"
    model: str = ""
    all_verses: bool = True
    verse_n: int = 50
    max_workers: int = 2
    # SHORTLIST: 1–100 = min score on 0–10 scale is N/10 (e.g. 70 → ≥7.0).
    relevance_threshold_pct: int = 70
    use_shortlist_for_synthesis: bool = True
    # Step 5 LLM request shape: one job per meaning-combo vs one job with all Lane entries.
    synthesis_mode: str = "combination"
    # SHORTLIST scoring: local CrossEncoder vs API LLM (provider/model separate from synthesis).
    shortlist_method: str = "cross_encoder"
    shortlist_llm_provider: str = "deepseek"
    shortlist_llm_model: str = ""


def _clamp_pct(n: object, default: int = 0) -> int:
    if n is None:
        return default
    try:
        x = int(round(float(n)))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, x))


def _clamp_positive(n: int, default: int, *, min_v: int = 1, max_v: int = 10000) -> int:
    try:
        x = int(n)
    except (TypeError, ValueError):
        return default
    if x < min_v:
        return min_v
    if x > max_v:
        return max_v
    return x


def load_step5_ui_settings() -> Step5UiSettings:
    try:
        raw = _SETTINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return Step5UiSettings()
    if not isinstance(data, dict):
        return Step5UiSettings()
    provider = str(data.get("provider") or "openai").strip().lower()
    if provider not in {"openai", "deepseek", "openrouter"}:
        provider = "openai"
    model = str(data.get("model") or "").strip()
    all_verses = bool(data.get("all_verses", True))
    verse_n = _clamp_positive(data.get("verse_n", 50), 50, max_v=100000)
    max_workers = _clamp_positive(data.get("max_workers", 2), 2, max_v=8)
    relevance_threshold_pct = _clamp_pct(data.get("relevance_threshold_pct", 70), 70)
    use_shortlist_for_synthesis = bool(data.get("use_shortlist_for_synthesis", True))
    sm = str(data.get("synthesis_mode") or "combination").strip().lower()
    if sm not in {"combination", "loaded"}:
        sm = "combination"
    sl_m = str(data.get("shortlist_method") or "cross_encoder").strip().lower()
    if sl_m not in {"cross_encoder", "llm"}:
        sl_m = "cross_encoder"
    sl_p = str(data.get("shortlist_llm_provider") or "deepseek").strip().lower()
    if sl_p not in {"deepseek", "openai", "openrouter"}:
        sl_p = "deepseek"
    sl_model = str(data.get("shortlist_llm_model") or "").strip()
    return Step5UiSettings(
        provider=provider,
        model=model,
        all_verses=all_verses,
        verse_n=verse_n,
        max_workers=max_workers,
        relevance_threshold_pct=relevance_threshold_pct,
        use_shortlist_for_synthesis=use_shortlist_for_synthesis,
        synthesis_mode=sm,
        shortlist_method=sl_m,
        shortlist_llm_provider=sl_p,
        shortlist_llm_model=sl_model,
    )


def save_step5_ui_settings(settings: Step5UiSettings) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    sm = str(settings.synthesis_mode or "combination").strip().lower()
    if sm not in {"combination", "loaded"}:
        sm = "combination"
    sl_m = str(settings.shortlist_method or "cross_encoder").strip().lower()
    if sl_m not in {"cross_encoder", "llm"}:
        sl_m = "cross_encoder"
    sl_p = str(settings.shortlist_llm_provider or "deepseek").strip().lower()
    if sl_p not in {"deepseek", "openai", "openrouter"}:
        sl_p = "deepseek"
    payload = {
        "provider": settings.provider.strip().lower() or "openai",
        "model": settings.model.strip(),
        "all_verses": bool(settings.all_verses),
        "verse_n": _clamp_positive(settings.verse_n, 50, max_v=100000),
        "max_workers": _clamp_positive(settings.max_workers, 2, max_v=8),
        "relevance_threshold_pct": _clamp_pct(settings.relevance_threshold_pct, 70),
        "use_shortlist_for_synthesis": bool(settings.use_shortlist_for_synthesis),
        "synthesis_mode": sm,
        "shortlist_method": sl_m,
        "shortlist_llm_provider": sl_p,
        "shortlist_llm_model": str(settings.shortlist_llm_model or "").strip(),
    }
    _SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
