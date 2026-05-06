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
        reasoning: str = "",
        orchestration_strategy: Optional[dict[str, Any]] = None,
        memory_layer: Optional[str] = None,
        memory_route: str = "none",
        llm_trace: Optional[dict[str, Any]] = None,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
    ):
        self.intent = intent
        self.tools = tools
        self.reasoning = reasoning
        self.orchestration_strategy = orchestration_strategy or {}
        self.memory_layer = memory_layer
        self.memory_route = memory_route
        self.llm_trace = dict(llm_trace or {})
        self.thinking_depth = thinking_depth


@dataclass
class MemoryGuidance:
    """Memory retrieval guidance from context routing."""

    recommended: bool
    route: str = "none"


__all__ = ["ContextDecision", "MemoryGuidance"]