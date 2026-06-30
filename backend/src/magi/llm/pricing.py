"""Cost calculation helpers for LLM usage metrics."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..config.loader import get_llm_provider_registry_file
from ..config.llm_registry import (
    LLMModelCostModel,
    LLMProviderRegistryModel,
    find_chat_model_meta,
    find_embedding_model_meta,
    find_image_generation_model_meta,
    load_llm_provider_registry,
)

TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class _ChatPricingRates:
    input: float | None
    cached_input: float | None
    cache_write: float | None
    output: float | None

    @property
    def has_billable_rate(self) -> bool:
        return any(
            rate is not None
            for rate in (
                self.input,
                self.cached_input,
                self.cache_write,
                self.output,
            )
        )


@dataclass(frozen=True)
class _ChatTokenBreakdown:
    uncached_input: int
    cached_input: int
    cache_write_5m: int
    cache_write_1h: int
    output: int


@lru_cache(maxsize=1)
def _load_provider_registry() -> LLMProviderRegistryModel:
    return load_llm_provider_registry(
        get_llm_provider_registry_file(),
        fallback=LLMProviderRegistryModel(),
    )


def _chat_pricing_rates(cost: LLMModelCostModel) -> _ChatPricingRates | None:
    rates = _ChatPricingRates(
        input=cost.input_per_million_tokens,
        cached_input=cost.cached_input_per_million_tokens,
        cache_write=cost.cache_write_per_million_tokens,
        output=cost.output_per_million_tokens,
    )
    return rates if rates.has_billable_rate else None


def _non_negative_count(value: int) -> int:
    return max(0, int(value or 0))


def _chat_token_breakdown(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    cache_write_1h_tokens: int,
) -> _ChatTokenBreakdown:
    prompt_count = _non_negative_count(prompt_tokens)
    completion_count = _non_negative_count(completion_tokens)
    cache_read_count = min(prompt_count, _non_negative_count(cache_read_tokens))
    remaining_prompt_count = max(0, prompt_count - cache_read_count)
    cache_write_count = min(remaining_prompt_count, _non_negative_count(cache_write_tokens))
    cache_write_1h_count = min(cache_write_count, _non_negative_count(cache_write_1h_tokens))

    return _ChatTokenBreakdown(
        uncached_input=max(0, remaining_prompt_count - cache_write_count),
        cached_input=cache_read_count,
        cache_write_5m=cache_write_count - cache_write_1h_count,
        cache_write_1h=cache_write_1h_count,
        output=completion_count,
    )


def _calculate_chat_total(
    *,
    rates: _ChatPricingRates,
    tokens: _ChatTokenBreakdown,
) -> float:
    five_minute_write_rate = (
        rates.cache_write if rates.cache_write is not None else rates.input or 0.0
    )
    # Anthropic bills a 1h cache write at 2x base input. Other vendors currently
    # do not report a 1h breakdown, so this derivation is only used when present.
    one_hour_write_rate = rates.input * 2 if rates.input is not None else five_minute_write_rate
    cached_input_rate = rates.cached_input if rates.cached_input is not None else rates.input or 0.0

    total = 0.0
    if rates.input is not None:
        total += tokens.uncached_input * rates.input
    if tokens.cached_input:
        total += tokens.cached_input * cached_input_rate
    if tokens.cache_write_5m:
        total += tokens.cache_write_5m * five_minute_write_rate
    if tokens.cache_write_1h:
        total += tokens.cache_write_1h * one_hour_write_rate
    if rates.output is not None:
        total += tokens.output * rates.output
    return total


def calculate_chat_cost(
    *,
    provider: str,
    provider_plan: str | None = None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
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
    model_meta = find_chat_model_meta(effective_registry, provider, model, provider_plan)
    if model_meta is None or model_meta.cost is None:
        return None, None

    cost = model_meta.cost
    rates = _chat_pricing_rates(cost)
    if rates is None:
        return None, None

    tokens = _chat_token_breakdown(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_write_1h_tokens=cache_write_1h_tokens,
    )
    total = _calculate_chat_total(rates=rates, tokens=tokens)

    currency = (cost.currency or "USD").upper()
    return total / TOKENS_PER_MILLION, currency


def calculate_embedding_cost(
    *,
    provider: str,
    provider_plan: str | None = None,
    model: str,
    prompt_tokens: int,
    registry: LLMProviderRegistryModel | None = None,
) -> tuple[float | None, str | None]:
    """Cost for an embedding request in the model's native currency.

    Embeddings are input-only (no completion tokens), so the cost is derived
    solely from ``input_per_million_tokens``. Returns ``(None, None)`` when the
    model has no pricing metadata.
    """
    effective_registry = registry or _load_provider_registry()
    meta = find_embedding_model_meta(effective_registry, provider, model, provider_plan)
    if meta is None or meta.cost is None:
        return None, None
    input_rate = meta.cost.input_per_million_tokens
    if input_rate is None:
        return None, None
    amount = max(0, int(prompt_tokens or 0)) * input_rate / TOKENS_PER_MILLION
    return amount, (meta.cost.currency or "USD").upper()


def calculate_image_generation_cost(
    *,
    provider: str,
    provider_plan: str | None = None,
    model: str,
    image_count: int,
    registry: LLMProviderRegistryModel | None = None,
) -> tuple[float | None, str | None]:
    """Cost for an image-generation request in the model's native currency.

    Image models are billed per image (``per_image``), so the cost is
    ``per_image × image_count``. Returns ``(None, None)`` when the model has no
    pricing metadata, so callers can tell "no pricing data" apart from a real 0.
    """
    effective_registry = registry or _load_provider_registry()
    meta = find_image_generation_model_meta(effective_registry, provider, model, provider_plan)
    if meta is None or meta.cost is None:
        return None, None
    per_image = meta.cost.per_image
    if per_image is None:
        return None, None
    amount = max(0, int(image_count or 0)) * per_image
    return amount, (meta.cost.currency or "USD").upper()


def calculate_chat_cost_usd(
    *,
    provider: str,
    provider_plan: str | None = None,
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
        provider_plan=provider_plan,
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
