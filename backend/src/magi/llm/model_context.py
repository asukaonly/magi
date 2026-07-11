"""Resolved model identity and context limits for one LLM invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelContextProfile:
    """Model identity and provider limits that must travel with an adapter."""

    provider_id: str
    model_id: str
    context_window: int | None
    max_output_tokens: int | None


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    """An adapter paired with the limits of the model it invokes."""

    adapter: Any
    context: ModelContextProfile


def unknown_model_context(adapter: Any | None) -> ModelContextProfile:
    """Describe an injected adapter whose provider limits are unavailable."""
    provider_id = str(
        getattr(adapter, "provider_name", None)
        or getattr(adapter, "provider", None)
        or "unknown"
    )
    model_id = str(
        getattr(adapter, "model_name", None)
        or getattr(adapter, "model_id", None)
        or "unknown"
    )
    return ModelContextProfile(
        provider_id=provider_id,
        model_id=model_id,
        context_window=None,
        max_output_tokens=None,
    )


__all__ = ["ModelContextProfile", "ResolvedModel", "unknown_model_context"]
