"""Persist Step 6 PARI agent, vector-store, and file-management UI settings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from src.chat.openai_documented_models import remap_removed_doc_model
from src.config import PROJECT_ROOT

_SETTINGS_PATH = PROJECT_ROOT / "data" / "chat" / "step6_ui_settings.json"

DEFAULT_PLAN_INSTRUCTIONS = (
    "You plan a structured theological report as markdown headings only.\n"
    "Output ONLY markdown lines starting with # or ## (no other prose).\n"
    "Use 4–8 top-level # sections; use ## for subsections where needed.\n"
    "The report will answer the user's refined question using retrieved knowledge files."
)

DEFAULT_ACT_INSTRUCTIONS = (
    "You write one section of a scholarly report on the Qur'an.\n"
    "Use file_search results from the session knowledge base: quote Arabic verses "
    "exactly as they appear there, with surah:ayah citation.\n"
    "Do not invent verses. Ground claims in file_search.\n"
    "Write in clear English; use markdown (##/###, bullets where useful).\n"
)

DEFAULT_REVIEW_INSTRUCTIONS = (
    "You revise and extend a draft report using file_search on the knowledge base only.\n"
    "Quote Arabic verses exactly as in files; cite surah:ayah. Do not invent content.\n"
    "Follow the user task in the message: cover missing verse references where relevant.\n"
)


@dataclass
class Step6UiSettings:
    """User-configurable Step 6 behavior. Empty instruction fields fall back to defaults."""

    model: str = ""
    temperature: float | None = None  # None → engine default (0.35 when allowed)
    shared_system_preamble: str = ""
    plan_instructions: str = ""
    act_instructions: str = ""
    review_instructions: str = ""
    extra_vector_store_ids: list[str] = field(default_factory=list)
    # Vector / file management (Load)
    replace_remote_knowledge_on_load: bool = True
    delete_openai_file_objects_after_detach: bool = True
    clear_local_knowledge_dir_before_load: bool = False
    # PARI
    max_review_rounds: int = 3
    appendix_max_chars: int = 1_500_000
    include_appendix: bool = True


def load_step6_ui_settings() -> Step6UiSettings:
    try:
        raw = _SETTINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return Step6UiSettings()
    if not isinstance(data, dict):
        return Step6UiSettings()
    model_raw = data.get("model")
    mstr = remap_removed_doc_model(
        model_raw.strip() if isinstance(model_raw, str) else ""
    )
    vs = data.get("extra_vector_store_ids")
    extra: list[str] = []
    if isinstance(vs, list):
        extra = [str(x).strip() for x in vs if str(x).strip()]
    temp_raw = data.get("temperature")
    temp: float | None = None
    if temp_raw is not None:
        try:
            temp = float(temp_raw)
        except (TypeError, ValueError):
            temp = None
    def _str(key: str) -> str:
        v = data.get(key)
        return str(v) if isinstance(v, str) else ""

    def _bool(key: str, default: bool) -> bool:
        v = data.get(key)
        return default if not isinstance(v, bool) else v

    def _int(key: str, default: int) -> int:
        v = data.get(key)
        try:
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    out = Step6UiSettings(
        model=mstr,
        temperature=temp,
        shared_system_preamble=_str("shared_system_preamble"),
        plan_instructions=_str("plan_instructions"),
        act_instructions=_str("act_instructions"),
        review_instructions=_str("review_instructions"),
        extra_vector_store_ids=extra,
        replace_remote_knowledge_on_load=_bool("replace_remote_knowledge_on_load", True),
        delete_openai_file_objects_after_detach=_bool(
            "delete_openai_file_objects_after_detach", True
        ),
        clear_local_knowledge_dir_before_load=_bool(
            "clear_local_knowledge_dir_before_load", False
        ),
        max_review_rounds=max(0, min(20, _int("max_review_rounds", 3))),
        appendix_max_chars=max(10_000, min(50_000_000, _int("appendix_max_chars", 1_500_000))),
        include_appendix=_bool("include_appendix", True),
    )
    raw_m = model_raw.strip() if isinstance(model_raw, str) else ""
    if mstr != raw_m:
        save_step6_ui_settings(out)
    return out


def save_step6_ui_settings(settings: Step6UiSettings) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    payload["model"] = settings.model.strip()
    payload["extra_vector_store_ids"] = list(settings.extra_vector_store_ids)
    _SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def merge_instruction_blocks(
    shared_preamble: str, override: str, default: str
) -> str:
    """Compose system instructions: optional shared preamble + (override or default)."""
    base = (override or "").strip() or (default or "").strip()
    pre = (shared_preamble or "").strip()
    if pre:
        return f"{pre}\n\n{base}"
    return base


def merged_file_search_vector_ids(
    session_vector_store_id: str, extras: list[str] | None
) -> list[str]:
    """Session store first, then extra admin/user stores; dedupe preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for x in [session_vector_store_id] + list(extras or []):
        s = (x or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out
