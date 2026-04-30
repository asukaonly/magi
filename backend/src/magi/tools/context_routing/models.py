"""Context routing result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ...config.models import ThinkingDepth


class ContextDecision:
    """Context decision result."""

    def __init__(
        self,
        intent: str,
        tools: list[str],
        deep_thinking: bool = False,
        reasoning: str = "",
        orchestration_strategy: Optional[dict[str, Any]] = None,
        memory_layer: Optional[str] = None,
        memory_route: str = "none",
        llm_trace: Optional[dict[str, Any]] = None,
        thinking_depth: Optional[ThinkingDepth] = None,
    ):
        self.intent = intent
        self.tools = tools
        self.reasoning = reasoning
        self.orchestration_strategy = orchestration_strategy or {}
        self.memory_layer = memory_layer
        self.memory_route = memory_route
        self.llm_trace = dict(llm_trace or {})

        if thinking_depth is not None:
            self.thinking_depth = thinking_depth
        elif deep_thinking:
            self.thinking_depth = ThinkingDepth.HIGH
        else:
            self.thinking_depth = ThinkingDepth.NONE

    @property
    def deep_thinking(self) -> bool:
        """Legacy accessor: True when thinking_depth is MEDIUM or above."""
        return self.thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW)


@dataclass
class MemoryGuidance:
    """Memory retrieval guidance from context routing."""

    recommended: bool
    route: str = "none"


__all__ = ["ContextDecision", "MemoryGuidance"]