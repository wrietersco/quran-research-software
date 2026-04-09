"""Model pricing + token budget defaults for Step 5 providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float
    output_per_1m: float
    max_input_tokens: int
    rpm_limit: int
    # Hard cap on completion tokens sent to the API (provider limits vary).
    max_output_tokens: int


_DEFAULT = ModelPricing(
    input_per_1m=0.0,
    output_per_1m=0.0,
    max_input_tokens=8000,
    rpm_limit=60,
    max_output_tokens=4096,
)

# Keep this list small; unknown models safely fallback to _DEFAULT.
# Rates are USD / 1M tokens (approximate; refresh from provider pricing pages).
_PRICING: dict[tuple[str, str], ModelPricing] = {
    ("openai", "gpt-4o-mini"): ModelPricing(0.15, 0.60, 12000, 60, 8192),
    ("openai", "gpt-4o"): ModelPricing(2.50, 10.00, 12000, 60, 8192),
    ("openai", "gpt-5-mini"): ModelPricing(0.25, 2.00, 12000, 60, 8192),
    ("openai", "gpt-5"): ModelPricing(1.25, 10.00, 12000, 60, 8192),
    # DeepSeek-V3.2: see https://api-docs.deepseek.com/quick_start/pricing
    ("deepseek", "deepseek-chat"): ModelPricing(0.28, 0.42, 120000, 60, 8192),
    ("deepseek", "deepseek-reasoner"): ModelPricing(0.28, 0.42, 120000, 30, 32768),
    # OpenRouter weighted averages (refresh from openrouter.ai if they drift).
    ("openrouter", "deepseek/deepseek-v3.2"): ModelPricing(
        0.221, 0.472, 120000, 60, 8192
    ),
}


def get_model_pricing(provider: str, model: str) -> ModelPricing:
    p = (provider or "").strip().lower()
    m = (model or "").strip()
    if p == "deepseek" and m.lower() in ("deepseek-v3.2", "deepseek-v3.2-chat", "deepseek/v3.2"):
        m = "deepseek-chat"
    if not m:
        return _DEFAULT
    hit = _PRICING.get((p, m))
    if hit is not None:
        return hit
    if p == "openai":
        return _PRICING.get(("openai", "gpt-4o-mini"), _DEFAULT)
    return _DEFAULT


def split_cost_usd(
    provider: str,
    model: str,
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> tuple[float, float, float]:
    pr = get_model_pricing(provider, model)
    pt = int(prompt_tokens or 0)
    ct = int(completion_tokens or 0)
    cin = (pt / 1_000_000.0) * pr.input_per_1m
    cout = (ct / 1_000_000.0) * pr.output_per_1m
    return cin, cout, cin + cout


def compute_cost_usd(
    provider: str,
    model: str,
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float:
    _, _, total = split_cost_usd(
        provider, model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    return total
