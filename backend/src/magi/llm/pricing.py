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
    """Calculate USD cost for a chat completion using registry pricing."""
    effective_registry = registry or _load_provider_registry()
    model_meta = find_chat_model_meta(effective_registry, provider, model)
    if model_meta is None or model_meta.cost is None:
        return None

    cost = model_meta.cost
    if cost.currency.upper() != "USD":
        return None

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
        return None

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

    return total / TOKENS_PER_MILLION