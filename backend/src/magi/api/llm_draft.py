"""Helpers for resolving temporary LLM draft settings."""

from __future__ import annotations

from typing import Callable

from ..config import get_config
from ..config.models import LLMProvider, LLMProviderSettings, LLMScenario, LLMSettings
from ..llm import create_llm_adapter


AdapterFactory = Callable[..., object]


def _resolve_runtime_provider_type(provider: LLMProviderSettings) -> str:
    provider_type = str(getattr(provider.provider_type, "value", provider.provider_type))
    if provider_type != LLMProvider.CUSTOM.value:
        return provider_type

    api_format = (provider.api_format or "openai").strip().lower()
    if api_format in {"openai", "anthropic"}:
        return api_format
    raise ValueError(f"Unsupported custom provider api_format: {provider.api_format}")


def build_adapter_from_provider(
    provider: LLMProviderSettings,
    *,
    model: str,
    timeout: int = 60,
    adapter_factory: AdapterFactory = create_llm_adapter,
) -> object:
    """Build a temporary adapter from provider settings."""
    if not provider.enabled:
        raise ValueError("LLM provider must be enabled before use")
    if not (provider.api_key or "").strip():
        raise ValueError("LLM provider API key is required")
    if not (model or "").strip():
        raise ValueError("LLM model is required")

    return adapter_factory(
        provider_type=_resolve_runtime_provider_type(provider),
        api_key=(provider.api_key or "").strip(),
        model=model.strip(),
        base_url=(provider.base_url or "").strip() or None,
        timeout=timeout,
    )


def resolve_adapter_for_scenario(
    scenario: LLMScenario,
    *,
    llm_settings: LLMSettings | None = None,
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
        adapter_factory=adapter_factory,
    )
