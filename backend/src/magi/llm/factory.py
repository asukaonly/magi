"""Unified LLM adapter factory."""

from __future__ import annotations

from .anthropic import AnthropicAdapter
from .base import LLMAdapter
from .openai import OpenAIAdapter


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
