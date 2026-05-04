"""Runtime LLM defaults derived from provider registry metadata."""

from __future__ import annotations

from typing import Any, Dict

from .constants import DEFAULT_MAX_TOKENS
from .llm_registry_models import LLMProviderRegistryModel


def build_runtime_llm_defaults(registry: LLMProviderRegistryModel) -> Dict[str, Any]:
    """Build runtime LLM defaults from provider registry metadata."""
    providers: Dict[str, Any] = {}

    empty_selection = {
        "provider_id": "",
        "model": "",
        "capability_override_enabled": False,
        "capabilities": {
            "vision": False,
            "image_output": False,
            "tool_calling": True,
            "reasoning": True,
            "embedding": False,
        },
        "limits": {
            "context_window": None,
            "max_output_tokens": None,
        },
        "provider_options": {},
        "embedding_dimension": None,
    }

    embedding_selection = {
        **empty_selection,
        "capabilities": {
            "vision": False,
            "image_output": False,
            "tool_calling": False,
            "reasoning": False,
            "embedding": True,
        },
    }

    image_generation_selection = {
        **empty_selection,
        "capabilities": {
            "vision": False,
            "image_output": True,
            "tool_calling": False,
            "reasoning": False,
            "embedding": False,
        },
    }

    return {
        "providers": providers,
        "selections": {
            "context_decider": dict(empty_selection),
            "core": dict(empty_selection),
            "memory_summarizer": dict(empty_selection),
            "embedding": embedding_selection,
            "image_generation": image_generation_selection,
        },
        "model_runtime_overrides": {},
        "temperature": 0.7,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "timeout": 60,
    }


__all__ = ["build_runtime_llm_defaults"]
