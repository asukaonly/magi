"""Secret masking helpers for system configuration payloads."""

from __future__ import annotations

from typing import Any, Optional

from ..routers.config_schemas import LLMProviderConfigModel, SystemConfigModel


def mask_api_key(api_key: str) -> str:
    """Mask an API key while preserving a short visible prefix."""
    if not api_key:
        return ""
    visible_chars = 6
    if len(api_key) <= visible_chars:
        return api_key[:3] + "***" if len(api_key) > 3 else "***"
    return api_key[:visible_chars] + "****"


def is_masked_api_key(api_key: Optional[str]) -> bool:
    """Return True only for explicit masked placeholders from UI payloads."""
    if not api_key:
        return False
    masked_patterns = ["***", "****", "*****"]
    if api_key in masked_patterns:
        return True
    return api_key.endswith("****") or api_key.endswith("***")


def normalize_masked_llm_provider_secrets(
    provider_id: str,
    provider: LLMProviderConfigModel,
    runtime_config: Any,
) -> LLMProviderConfigModel:
    """Replace masked provider credentials with backend-owned stored values."""
    normalized = provider.model_copy(deep=True)
    runtime_provider = runtime_config.llm.providers.get(provider_id)
    if is_masked_api_key(normalized.api_key):
        normalized.api_key = runtime_provider.api_key if runtime_provider is not None else None

    runtime_services = getattr(runtime_provider, "services", None)
    for service_name in ("chat", "embedding", "image_generation", "tts"):
        service = getattr(normalized.services, service_name)
        if not is_masked_api_key(service.api_key):
            continue
        runtime_service = getattr(runtime_services, service_name, None)
        service.api_key = runtime_service.api_key if runtime_service is not None else None

    return normalized


def normalize_masked_secrets(config: SystemConfigModel, runtime_config: Any) -> SystemConfigModel:
    normalized = SystemConfigModel.model_validate(config.model_dump())

    for provider_id, provider in normalized.llm.providers.items():
        normalized.llm.providers[provider_id] = normalize_masked_llm_provider_secrets(
            provider_id,
            provider,
            runtime_config,
        )

    weather_api_key = normalized.tools.builtIn.weather.apiKey
    if is_masked_api_key(weather_api_key):
        weather_provider = normalized.tools.builtIn.weather.provider
        runtime_weather = runtime_config.tools.weather.providers.get(weather_provider)
        normalized.tools.builtIn.weather.apiKey = (
            runtime_weather.api_key if runtime_weather is not None else None
        )

    web_search_api_key = normalized.tools.builtIn.webSearch.apiKey
    if is_masked_api_key(web_search_api_key):
        web_search_provider = normalized.tools.builtIn.webSearch.provider
        runtime_web_search = runtime_config.tools.web_search.providers.get(web_search_provider)
        normalized.tools.builtIn.webSearch.apiKey = (
            runtime_web_search.api_key if runtime_web_search is not None else None
        )

    return normalized


__all__ = [
    "is_masked_api_key",
    "mask_api_key",
    "normalize_masked_llm_provider_secrets",
    "normalize_masked_secrets",
]
