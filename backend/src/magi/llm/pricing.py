"""Cost calculation helpers for LLM usage metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from math import isfinite
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ..config.loader import get_llm_provider_registry_file
from ..config.llm_registry import (
    LLMModelCostModel,
    LLMProviderRegistryModel,
    find_chat_model_meta,
    find_embedding_model_meta,
    find_image_generation_model_meta,
    load_llm_provider_registry,
)
from ..config.pricing_models import LLMPricingRule, LLMTokenRates

TOKENS_PER_MILLION = 1_000_000


@lru_cache(maxsize=1)
def _load_provider_registry() -> LLMProviderRegistryModel:
    return load_llm_provider_registry(
        get_llm_provider_registry_file(), fallback=LLMProviderRegistryModel(),
    )


def _rule_matches(
    rule: LLMPricingRule, *, prompt: int, output: int, at: datetime,
    host: str, service_tier: str, thinking: bool | None, cache_mode: str,
    inference_geo: str,
) -> bool:
    return not (
        (rule.min_input_tokens is not None and prompt < rule.min_input_tokens)
        or (rule.max_input_tokens is not None and prompt > rule.max_input_tokens)
        or (rule.min_output_tokens is not None and output < rule.min_output_tokens)
        or (rule.max_output_tokens is not None and output > rule.max_output_tokens)
        or (rule.starts_at is not None and at < rule.starts_at)
        or (rule.ends_at is not None and at >= rule.ends_at)
        or (rule.endpoint_hosts and host not in rule.endpoint_hosts)
        or (rule.service_tiers and service_tier not in rule.service_tiers)
        or (rule.thinking is not None and thinking != rule.thinking)
        or (rule.cache_mode is not None and cache_mode != rule.cache_mode)
        or (rule.inference_geo is not None and inference_geo != rule.inference_geo)
    )


def _resolved_rates(
    cost: LLMModelCostModel, *, prompt: int, output: int, at: datetime,
    host: str, service_tier: str, thinking: bool | None, cache_mode: str,
    inference_geo: str,
) -> tuple[LLMTokenRates, float] | None:
    if cost.endpoint_hosts and host not in cost.endpoint_hosts:
        return None
    rates = LLMTokenRates.model_validate(cost.model_dump())
    multiplier = 1.0
    matched_tier = service_tier in {"default", "standard", "auto"}
    for rule in cost.rules:
        args = dict(prompt=prompt, output=output, at=at, host=host,
                    service_tier=service_tier, thinking=thinking,
                    cache_mode=cache_mode, inference_geo=inference_geo)
        if rule.thinking is not None and thinking is None:
            # An unknown thinking mode must not silently select the cheaper rate.
            if _rule_matches(rule, **{**args, "thinking": rule.thinking}):
                return None
        if _rule_matches(rule, **args):
            rates = rates.model_copy(update=rule.rates)
            multiplier *= rule.multiplier
            matched_tier |= bool(rule.service_tiers)
    if not matched_tier:
        return None
    peak = cost.peak_pricing
    if peak:
        holiday_date = at.astimezone(ZoneInfo("Asia/Shanghai")).date()
        minute = at.hour * 60 + at.minute
        if (at.weekday() < 5
                and any(start <= minute < end for start, end in peak.utc_windows)):
            if holiday_date.year not in peak.calendar_years:
                return None
            if not any(start <= holiday_date <= end for start, end in peak.holidays):
                multiplier *= peak.multiplier
    return rates, multiplier


def calculate_chat_cost(
    *, provider: str, model: str, prompt_tokens: int, completion_tokens: int,
    provider_plan: str | None = None,
    cache_read_tokens: int = 0, cache_write_tokens: int = 0,
    cache_write_1h_tokens: int = 0, cache_write_12h_tokens: int = 0,
    requested_at: float | None = None, endpoint_host: str | None = None,
    service_tier: str = "default", thinking: bool | None = None,
    cache_mode: str = "implicit", inference_geo: str = "global",
    cost_override: LLMModelCostModel | None = None,
    registry: LLMProviderRegistryModel | None = None,
) -> tuple[float | None, str | None]:
    """Price each request using total input length, exclusive cache buckets and UTC time.

    All tokens use the selected tier; this is not progressive slab billing.
    Missing rates or unsupported billing conditions return an unknown amount.
    Storage of separately created explicit caches is not a per-read token charge.
    """
    effective_registry = registry or _load_provider_registry()
    meta = find_chat_model_meta(effective_registry, provider, model, provider_plan)
    cost = cost_override or (meta.cost if meta else None)
    if cost is None:
        return None, None
    counts = (prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens,
              cache_write_1h_tokens, cache_write_12h_tokens)
    if (any(count < 0 for count in counts)
            or cache_read_tokens + cache_write_tokens > prompt_tokens
            or cache_write_1h_tokens + cache_write_12h_tokens > cache_write_tokens):
        return None, None
    if requested_at is not None and not isfinite(requested_at):
        return None, None
    try:
        at = datetime.fromtimestamp(requested_at, timezone.utc) if requested_at is not None else datetime.now(timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, None
    if endpoint_host is None:
        provider_meta = next((item for item in effective_registry.providers if item.id == provider), None)
        endpoint_host = urlsplit(provider_meta.default_base_url or "").hostname if provider_meta else ""
    resolved = _resolved_rates(
        cost, prompt=prompt_tokens, output=completion_tokens, at=at,
        host=endpoint_host or "", service_tier=service_tier, thinking=thinking,
        cache_mode=cache_mode, inference_geo=inference_geo,
    )
    if resolved is None:
        return None, None
    rates, multiplier = resolved
    buckets = (
        (prompt_tokens - cache_read_tokens - cache_write_tokens, rates.input_per_million_tokens),
        (cache_read_tokens, rates.cached_input_per_million_tokens),
        (cache_write_tokens - cache_write_1h_tokens - cache_write_12h_tokens, rates.cache_write_per_million_tokens),
        (cache_write_1h_tokens, rates.cache_write_1h_per_million_tokens),
        (cache_write_12h_tokens, rates.cache_write_12h_per_million_tokens),
        (completion_tokens, rates.output_per_million_tokens),
    )
    if not any(rate is not None for _, rate in buckets) or any(count and rate is None for count, rate in buckets):
        return None, None
    total = sum(count * rate for count, rate in buckets if rate is not None) * multiplier / TOKENS_PER_MILLION
    return (total, (rates.currency or "USD").upper()) if isfinite(total) else (None, None)


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
