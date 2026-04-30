"""Container-backed providers for LLM runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.container import get_container

if TYPE_CHECKING:
    from .scenario_pool import ScenarioLLMPool


def get_scenario_llm_pool() -> "ScenarioLLMPool":
    """Return the active scenario LLM pool binding."""
    provider = get_container().scenario_llm_pool
    instance = provider()
    if instance is None:
        raise RuntimeError("scenario_llm_pool binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError("scenario_llm_pool binding is not initialized")
    return instance
