"""Unified LLM adapter factory."""

from __future__ import annotations

import logging

from ..config import AppConfig
from ..config.models import LLMProvider
from .anthropic import AnthropicAdapter
from .base import LLMAdapter
from .openai import OpenAIAdapter
from .scenario_pool import LLMScenario, ScenarioLLMPool

logger = logging.getLogger(__name__)


# Provider names that require the dedicated AnthropicAdapter (Anthropic
# Messages API). Anything else maps onto the OpenAI-compatible adapter:
# the *transport* shape is OpenAI Chat Completions and vendor-level
# differences (reasoning/thinking payloads, tool-calling format, ...)
# are resolved later via ``ModelVendor`` at request time.
_ANTHROPIC_ADAPTER_PROVIDERS = frozenset({LLMProvider.ANTHROPIC.value})

# All known providers that flow through the OpenAI-compatible adapter.
# Custom providers are accepted because their transport is OpenAI-shape
# regardless of which vendor's models they proxy.
_OPENAI_COMPATIBLE_PROVIDERS = frozenset(
    member.value for member in LLMProvider if member.value not in _ANTHROPIC_ADAPTER_PROVIDERS
)


def create_llm_adapter(
    *,
    provider_type: str,
    api_key: str,
    model: str,
    base_url: str | None = None,
    provider_plan: str | None = None,
    timeout: int = 60,
    embedding_dimension: int | None = None,
    proxy_url: str | None = None,
) -> LLMAdapter:
    """Create an adapter from explicit provider settings."""
    provider = provider_type.lower().strip()

    if not api_key and provider != LLMProvider.CUSTOM.value:
        raise ValueError("LLM API key not configured")
    if provider == LLMProvider.CUSTOM.value and not str(base_url or "").strip():
        raise ValueError("Custom LLM base URL not configured")

    if provider in _ANTHROPIC_ADAPTER_PROVIDERS:
        return AnthropicAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_plan=provider_plan,
            timeout=timeout,
            proxy_url=proxy_url,
        )

    if provider in _OPENAI_COMPATIBLE_PROVIDERS:
        return OpenAIAdapter(
            api_key=api_key,
            model=model,
            provider=provider,
            base_url=base_url,
            provider_plan=provider_plan,
            timeout=timeout,
            embedding_dimension=embedding_dimension,
            proxy_url=proxy_url,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")


def create_scenario_llm_pool(config: AppConfig) -> ScenarioLLMPool:
    """Create a scenario-based LLM pool from application config."""
    return ScenarioLLMPool(config=config, adapter_factory=create_llm_adapter)


def create_core_llm_adapter(llm_pool: ScenarioLLMPool) -> LLMAdapter:
    """Get the core LLM adapter from a scenario pool."""
    llm_adapter = llm_pool.get(LLMScenario.CORE)
    logger.info(
        "Creating LLM adapter | Provider: %s | Model: %s",
        getattr(llm_adapter, "provider_name", "unknown"),
        getattr(llm_adapter, "model_name", "unknown"),
    )
    return llm_adapter


REQUIRED_RUNTIME_LLM_SCENARIOS = (
    LLMScenario.CONTEXT_DECIDER.value,
    LLMScenario.CORE.value,
)


def is_llm_selection_pending(config: AppConfig) -> bool:
    """Check whether required LLM scenario selections are incomplete."""
    for scenario_name in REQUIRED_RUNTIME_LLM_SCENARIOS:
        selection = config.llm.selections.get(scenario_name)
        if selection is None:
            return True
        if not str(selection.provider_id or "").strip():
            return True
        if not str(selection.model or "").strip():
            return True
    return False
