"""Thin LLM wrapper for L2 prompt execution and JSON-safe parsing."""

from __future__ import annotations

from ...llm import ScenarioLLMPool
from .llm_common import L2LLMCommonMixin
from .llm_entity_resolution import L2LLMEntityResolutionMixin
from .llm_extraction import L2LLMExtractionMixin
from .llm_json_client import L2LLMJsonClientMixin


class L2LLMService(
    L2LLMJsonClientMixin,
    L2LLMCommonMixin,
    L2LLMExtractionMixin,
    L2LLMEntityResolutionMixin,
):
    """Executes L2 prompts with conservative failure handling."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool


__all__ = [
    "L2LLMService",
    "L2LLMCommonMixin",
    "L2LLMExtractionMixin",
    "L2LLMEntityResolutionMixin",
]
