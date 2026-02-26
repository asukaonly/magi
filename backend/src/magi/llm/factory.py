"""
Unified LLM adapter factory.
"""

from __future__ import annotations

from typing import Optional

from ..config import AppConfig, get_config
from .anthropic import AnthropicAdapter
from .base import LLMAdapter
from .openai import OpenAIAdapter


def create_llm_adapter(config: Optional[AppConfig] = None) -> LLMAdapter:
    """
    Create LLM adapter from runtime app config.

    Args:
        config: Optional app config. When omitted, runtime config is used.

    Returns:
        Initialized LLM adapter.
    """
    app_config = config or get_config()
    llm_config = app_config.llm
    provider = llm_config.provider.value
    api_key = llm_config.api_key
    model = llm_config.model
    base_url = llm_config.base_url

    if not api_key:
        raise ValueError("LLM API key not configured")

    if provider == "anthropic":
        return AnthropicAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

    if provider in ("openai", "glm"):
        return OpenAIAdapter(
            api_key=api_key,
            model=model,
            provider=provider,
            base_url=base_url,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")
