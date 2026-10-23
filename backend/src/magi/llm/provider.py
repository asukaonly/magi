"""Container-backed providers for LLM runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.container import require_binding

if TYPE_CHECKING:
    from .scenario_pool import ScenarioLLMPool


def get_scenario_llm_pool() -> "ScenarioLLMPool":
    """Return the active scenario LLM pool binding."""
    return require_binding("scenario_llm_pool")
