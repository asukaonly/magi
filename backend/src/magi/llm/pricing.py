"""Cost calculation helpers for LLM usage metrics."""

from __future__ import annotations

from functools import lru_cache

from ..config.loader import get_llm_provider_registry_file
from ..config.llm_registry import (
    LLMProviderRegistryModel,
    find_chat_model_meta,
    load_llm_provider_registry,
)

TOKENS_PER_MILLION = 1_000_000


@lru_cache(maxsize=1)
def _load_provider_registry() -> LLMProviderRegistryModel:
    return load_llm_provider_registry(
        get_llm_provider_registry_file(),
        fallback=LLMProviderRegistryModel(),
    )


def calculate_chat_cost(
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    registry: LLMProviderRegistryModel | None = None,
) -> tuple[float | None, str | None]:
    """Calculate a chat completion cost in the model's native billing currency.

    Returns ``(amount, currency)`` where ``currency`` is the upper-cased ISO code
    declared in the registry (e.g. ``"USD"``, ``"CNY"``). Returns ``(None, None)``
    when the model has no pricing metadata, so callers can tell "no pricing data"
    apart from a genuine zero cost.

    Unlike the legacy :func:`calculate_chat_cost_usd`, this does NOT drop non-USD
    pricing — the amount is reported in whatever currency the model is billed in,
    and conversion (if any) is left to the presentation layer.
    """
    effective_registry = registry or _load_provider_registry()
    model_meta = find_chat_model_meta(effective_registry, provider, model)
    if model_meta is None or model_meta.cost is None:
        return None, None

    cost = model_meta.cost
    input_rate = cost.input_per_million_tokens
    cached_input_rate = cost.cached_input_per_million_tokens
    cache_write_rate = cost.cache_write_per_million_tokens
    output_rate = cost.output_per_million_tokens
    if (
        input_rate is None
        and cached_input_rate is None
        and cache_write_rate is None
        and output_rate is None
    ):
        return None, None

    prompt_count = max(0, int(prompt_tokens or 0))
    completion_count = max(0, int(completion_tokens or 0))
    cache_read_count = min(prompt_count, max(0, int(cache_read_tokens or 0)))
    remaining_prompt_count = max(0, prompt_count - cache_read_count)
    cache_write_count = min(remaining_prompt_count, max(0, int(cache_write_tokens or 0)))
    uncached_input_count = max(0, remaining_prompt_count - cache_write_count)

    total = 0.0
    if input_rate is not None:
        total += uncached_input_count * input_rate
    if cache_read_count:
        total += cache_read_count * (cached_input_rate if cached_input_rate is not None else input_rate or 0.0)
    if cache_write_count:
        total += cache_write_count * (cache_write_rate if cache_write_rate is not None else input_rate or 0.0)
    if output_rate is not None:
        total += completion_count * output_rate

    currency = (cost.currency or "USD").upper()
    return total / TOKENS_PER_MILLION, currency


def calculate_chat_cost_usd(
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    registry: LLMProviderRegistryModel | None = None,
) -> float | None:
    """Calculate USD cost for a chat completion, or ``None`` if not USD-priced.

    Back-compat wrapper around :func:`calculate_chat_cost`; only returns a value
    for models billed in USD. New callers should prefer
    :func:`calculate_chat_cost` so non-USD currencies are not silently dropped.
    """
    amount, currency = calculate_chat_cost(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        registry=registry,
    )
    if amount is None or currency != "USD":
        return None
    return amount