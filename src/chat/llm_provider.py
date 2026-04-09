"""Provider-agnostic Chat Completions wrapper for Step 5.

OpenRouter: set OPENROUTER_API_KEY; optional OPENROUTER_BASE_URL (default
https://openrouter.ai/api/v1), OPENROUTER_MODEL_STEP5, OPENROUTER_REASONING=1
for DeepSeek-style reasoning. Optional HTTP-Referer / X-Title on the client
are not required; pass default_headers to OpenAI() if you add them later.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from src.chat.llm_pricing import compute_cost_usd, get_model_pricing

_tls_openai: threading.local = threading.local()


def _openai_client_for_config(cfg: LlmProviderConfig):
    """One ``OpenAI`` instance per worker thread (avoids new client/pool per request)."""
    key = (cfg.api_key, (cfg.base_url or "").strip())
    cached = getattr(_tls_openai, "client", None)
    cached_key = getattr(_tls_openai, "cfg_key", None)
    if cached is not None and cached_key == key:
        return cached
    from openai import OpenAI

    client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    _tls_openai.client = client
    _tls_openai.cfg_key = key
    return client


@dataclass(frozen=True)
class LlmProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    max_input_tokens: int
    rpm_limit: int
    max_output_tokens: int


@dataclass(frozen=True)
class LlmCallResult:
    text: str
    model: str
    response_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: float


class LlmProviderError(Exception):
    pass


def default_model_for_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    if p == "deepseek":
        return (os.environ.get("DEEPSEEK_MODEL_STEP5") or "deepseek-chat").strip()
    if p == "openrouter":
        return (
            os.environ.get("OPENROUTER_MODEL_STEP5") or "deepseek/deepseek-v3.2"
        ).strip()
    return (os.environ.get("OPENAI_MODEL_STEP5") or "gpt-4o-mini").strip()


def default_shortlist_llm_model(provider: str) -> str:
    """Default chat model for Step 5 SHORTLIST (LLM mode); separate from synthesis defaults."""
    p = (provider or "").strip().lower()
    if p == "deepseek":
        return (os.environ.get("DEEPSEEK_MODEL_SHORTLIST") or "deepseek-v3.2").strip()
    if p == "openrouter":
        return (
            os.environ.get("OPENROUTER_MODEL_SHORTLIST")
            or os.environ.get("OPENROUTER_MODEL_STEP5")
            or "deepseek/deepseek-v3.2"
        ).strip()
    return (os.environ.get("OPENAI_MODEL_SHORTLIST") or "gpt-4o-mini").strip()


def deepseek_api_model_id(user_model: str) -> str:
    """Map UI / env model names to the DeepSeek API ``model`` field.

    The official API documents V3-class chat under the id ``deepseek-chat``; there is no
    separate ``deepseek-v3.2`` parameter. Selecting ``deepseek-v3.2`` in the UI still calls
    that same endpoint.
    """
    m = (user_model or "").strip().lower()
    if m in ("deepseek-v3.2", "deepseek-v3.2-chat", "deepseek/v3.2"):
        return "deepseek-chat"
    out = (user_model or "").strip()
    return out if out else "deepseek-chat"


def resolve_provider_config(provider: str, model: str | None = None) -> LlmProviderConfig:
    p = (provider or "").strip().lower()
    if p not in {"openai", "deepseek", "openrouter"}:
        raise LlmProviderError(f"Unsupported provider: {provider!r}")
    chosen_model = (model or "").strip() or default_model_for_provider(p)
    if p == "deepseek":
        api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        # Docs: https://api.deepseek.com or https://api.deepseek.com/v1 (OpenAI-compatible).
        base_url = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").strip()
        api_model = deepseek_api_model_id(chosen_model)
    elif p == "openrouter":
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        base_url = (
            os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        ).strip()
        api_model = chosen_model
    else:
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
        api_model = chosen_model
    if not api_key:
        env_name = {
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }.get(p, "OPENAI_API_KEY")
        raise LlmProviderError(f"{env_name} is not set.")
    pricing = get_model_pricing(p, api_model if p == "deepseek" else chosen_model)
    return LlmProviderConfig(
        provider=p,
        model=api_model,
        api_key=api_key,
        base_url=base_url,
        max_input_tokens=pricing.max_input_tokens,
        rpm_limit=pricing.rpm_limit,
        max_output_tokens=pricing.max_output_tokens,
    )


def _choice_message_text(choice: object) -> str | None:
    """Best-effort extract assistant text from a chat completion choice."""
    if choice is None:
        return None
    msg = getattr(choice, "message", None)
    if msg is None:
        return None
    content = getattr(msg, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def _wants_deepseek_style_json(cfg: LlmProviderConfig) -> bool:
    if cfg.provider == "deepseek":
        return True
    if cfg.provider == "openrouter" and cfg.model.strip().lower().startswith("deepseek/"):
        return True
    return False


def shortlist_needs_deepseek_json_preamble(cfg: LlmProviderConfig) -> bool:
    """Whether Step 5 SHORTLIST should use the DeepSeek-style JSON preamble with ``call_chat_completion``."""
    return _wants_deepseek_style_json(cfg)


def _openrouter_reasoning_extra_body() -> dict[str, object] | None:
    v = (os.environ.get("OPENROUTER_REASONING") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return {"reasoning": {"enabled": True}}
    return None


def call_chat_completion(
    cfg: LlmProviderConfig,
    *,
    system_prompt: str,
    user_json_payload: str,
    deepseek_json_preamble: str | None = None,
) -> LlmCallResult:
    try:
        client = _openai_client_for_config(cfg)
    except ImportError as e:
        raise LlmProviderError("Install the OpenAI SDK: pip install openai") from e
    ds_json = _wants_deepseek_style_json(cfg)
    # DeepSeek JSON mode: must mention "json" and set max_tokens to avoid runaway / empty output.
    # See https://api-docs.deepseek.com/guides/json_mode
    user_content = user_json_payload
    if ds_json:
        if deepseek_json_preamble is not None:
            preamble = deepseek_json_preamble.strip()
            user_content = preamble + "\n\n" + user_json_payload
        else:
            user_content = (
                "Output must be a single valid json object only, with keys "
                "possibility_score, exegesis, symbolic_reasoning. "
                "Do not use markdown fences or any text outside the json object.\n\n"
                + user_json_payload
            )

    max_out = max(256, min(131072, int(cfg.max_output_tokens)))
    base_kwargs: dict = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_out,
    }
    if cfg.provider == "openrouter":
        ob = _openrouter_reasoning_extra_body()
        if ob is not None:
            base_kwargs["extra_body"] = ob

    resp = None
    # 1) JSON mode (OpenAI + DeepSeek documented)
    try:
        resp = client.chat.completions.create(
            **base_kwargs,
            response_format={"type": "json_object"},
        )
    except Exception as e1:
        if ds_json:
            # Some stacks reject json_object; retry plain chat (prompt still demands JSON).
            try:
                resp = client.chat.completions.create(**base_kwargs)
            except Exception as e2:
                raise LlmProviderError(
                    f"LLM request failed (json mode: {e1!r}; plain: {e2!r})"
                ) from e2
        else:
            raise LlmProviderError(f"LLM request failed: {e1}") from e1

    choice = resp.choices[0] if resp and resp.choices else None
    text = _choice_message_text(choice)
    finish = getattr(choice, "finish_reason", None) if choice else None

    if (not text) and ds_json:
        try:
            resp = client.chat.completions.create(**base_kwargs)
        except Exception as e3:
            raise LlmProviderError(
                f"Empty model content (finish_reason={finish!r}); retry failed: {e3!r}"
            ) from e3
        choice = resp.choices[0] if resp and resp.choices else None
        text = _choice_message_text(choice)
        finish = getattr(choice, "finish_reason", None) if choice else None

    if not text:
        raise LlmProviderError(
            f"Empty response from provider (finish_reason={finish!r}). "
            f"For DeepSeek-style JSON mode, try increasing max_output_tokens or shorten the system prompt."
        )

    usage = getattr(resp, "usage", None)
    pt = getattr(usage, "prompt_tokens", None) if usage else None
    ct = getattr(usage, "completion_tokens", None) if usage else None
    tt = getattr(usage, "total_tokens", None) if usage else None
    return LlmCallResult(
        text=str(text),
        model=getattr(resp, "model", None) or cfg.model,
        response_id=getattr(resp, "id", None),
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        cost_usd=compute_cost_usd(
            cfg.provider, cfg.model, prompt_tokens=pt, completion_tokens=ct
        ),
    )
