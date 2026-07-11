"""Helpers for resolving temporary LLM draft settings."""

from __future__ import annotations

from typing import Callable

from ..config import get_config
from ..config.models import LLMProvider, LLMProviderSettings, LLMScenario, LLMSettings
from .factory import create_llm_adapter

AdapterFactory = Callable[..., object]
BUILTIN_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "grok": "https://api.x.ai/v1",
    "deepseek": "https://api.deepseek.com",
    "kimi": "https://api.moonshot.cn/v1",
    "minimax": "https://api.minimaxi.com/v1",
}


def _resolve_runtime_provider_type(provider: LLMProviderSettings) -> str:
    provider_type = str(getattr(provider.provider_type, "value", provider.provider_type))
    if provider_type != LLMProvider.CUSTOM.value:
        return provider_type

    api_format = (provider.api_format or "openai").strip().lower()
    if api_format == "openai":
        return LLMProvider.CUSTOM.value
    if api_format == "anthropic":
        return LLMProvider.ANTHROPIC.value
    raise ValueError(f"Unsupported custom provider api_format: {provider.api_format}")


def _resolve_default_base_url(
    provider: LLMProviderSettings, explicit_default: str | None = None
) -> str | None:
    provider_type = str(getattr(provider.provider_type, "value", provider.provider_type))
    if explicit_default:
        return explicit_default
    if provider_type == LLMProvider.GLM.value and provider.provider_plan == "codeplan":
        return "https://open.bigmodel.cn/api/coding/paas/v4"
    return BUILTIN_DEFAULT_BASE_URLS.get(provider_type)


def build_adapter_from_provider(
    provider: LLMProviderSettings,
    *,
    model: str,
    timeout: int = 60,
    default_base_url: str | None = None,
    adapter_factory: AdapterFactory = create_llm_adapter,
    proxy_url: str | None = None,
) -> object:
    """Build a temporary adapter from provider settings."""
    if not provider.enabled:
        raise ValueError("LLM provider must be enabled before use")
    chat_service = provider.services.chat
    if not chat_service.enabled:
        raise ValueError("LLM provider chat service must be enabled before use")
    runtime_provider_type = _resolve_runtime_provider_type(provider)
    api_key = (chat_service.api_key or provider.api_key or "").strip()
    base_url = (chat_service.base_url or provider.base_url or "").strip()
    if not api_key and runtime_provider_type != LLMProvider.CUSTOM.value:
        raise ValueError("LLM provider API key is required")
    if runtime_provider_type == LLMProvider.CUSTOM.value and not base_url:
        raise ValueError("Custom LLM provider base URL is required")
    if not (model or "").strip():
        raise ValueError("LLM model is required")

    if proxy_url is None:
        config = get_config()
        proxy_url = config.network.proxy_url() if hasattr(config, "network") else None

    adapter_kwargs = {
        "provider_type": runtime_provider_type,
        "api_key": api_key,
        "model": model.strip(),
        "base_url": base_url or _resolve_default_base_url(provider, default_base_url) or None,
        "timeout": timeout,
        "proxy_url": proxy_url,
    }
    if provider.provider_plan:
        adapter_kwargs["provider_plan"] = provider.provider_plan
    return adapter_factory(**adapter_kwargs)


def resolve_adapter_for_scenario(
    scenario: LLMScenario,
    *,
    llm_settings: LLMSettings | None = None,
    default_base_url: str | None = None,
    adapter_factory: AdapterFactory = create_llm_adapter,
) -> object:
    """Resolve an adapter from draft settings or persisted config."""
    effective_settings = llm_settings or get_config().llm
    selection = effective_settings.selections.get(scenario.value)
    if selection is None:
        raise ValueError(f"Missing LLM selection for scenario '{scenario.value}'")
    if not selection.provider_id:
        raise ValueError(f"LLM scenario '{scenario.value}' is missing a provider")

    provider = effective_settings.providers.get(selection.provider_id)
    if provider is None:
        raise ValueError(
            f"LLM scenario '{scenario.value}' references unknown provider '{selection.provider_id}'"
        )

    return build_adapter_from_provider(
        provider,
        model=selection.model,
        timeout=effective_settings.timeout,
        default_base_url=default_base_url,
        adapter_factory=adapter_factory,
    )
