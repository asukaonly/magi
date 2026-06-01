"""Context routing result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ...config.models import ThinkingDepth


class ContextDecision:
    """Context decision result.

    Carries both tool/intent routing and persona-routing (register, active
    signature triggers, quiet-hour hints) so the chat coordinator can build
    a coherent turn plan from a single LLM call instead of running an
    independent keyword classifier inside PersonaTurnPlanner.

    The persona routing fields are optional: when the LLM omits them or
    the decider is unavailable, downstream PersonaTurnPlanner falls back
    to its keyword-based selection path.
    """

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
        register: Optional[str] = None,
        active_trigger_ids: Optional[list[str]] = None,
        situation_strength: str = "ordinary",
        quiet_hour_hints: Optional[list[str]] = None,
    ):
        self.intent = intent
        self.tools = tools
        self.reasoning = reasoning
        self.orchestration_strategy = orchestration_strategy or {}
        self.memory_layer = memory_layer
        self.memory_route = memory_route
        self.llm_trace = dict(llm_trace or {})
        self.thinking_depth = thinking_depth
        # Persona routing fields populated by the unified router (P1).
        # Empty/None means "no LLM-supplied routing; fall back to keywords."
        self.register: Optional[str] = register
        self.active_trigger_ids: list[str] = list(active_trigger_ids or [])
        self.situation_strength: str = situation_strength
        self.quiet_hour_hints: list[str] = list(quiet_hour_hints or [])


@dataclass
class MemoryGuidance:
    """Memory retrieval guidance from context routing."""

    recommended: bool
    route: str = "none"


__all__ = ["ContextDecision", "MemoryGuidance"]