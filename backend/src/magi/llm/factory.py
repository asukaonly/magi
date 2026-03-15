"""Unified LLM adapter factory."""

from __future__ import annotations

import logging

from ..config import AppConfig
from .anthropic import AnthropicAdapter
from .base import LLMAdapter
from .openai import OpenAIAdapter
from .scenario_pool import LLMScenario, ScenarioLLMPool

logger = logging.getLogger(__name__)


def create_llm_adapter(
    *,
    provider_type: str,
    api_key: str,
    model: str,
    base_url: str | None = None,
    timeout: int = 60,
) -> LLMAdapter:
    """Create an adapter from explicit provider settings."""
    provider = provider_type.lower().strip()

    if not api_key:
        raise ValueError("LLM API key not configured")

    if provider == "anthropic":
        return AnthropicAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
        )

    if provider in {"openai", "glm", "gemini", "deepseek", "kimi", "minimax"}:
        return OpenAIAdapter(
            api_key=api_key,
            model=model,
            provider=provider,
            base_url=base_url,
            timeout=timeout,
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
