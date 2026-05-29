"""Rule-based fallback routing for ContextDecider.

This is the *fallback* path used when the LLM router fails / times out.
By design we keep it tiny: only routes that we can decide structurally
(based on context state, not the user's wording) belong here. Anything
else returns a conservative ``chat`` profile with no tools — the safer
default than guessing a category from substring matches.

Historically this module grew several keyword tables (research /
files / web / shell / skills) that drifted with each new user phrase
and language. Those were removed; if you find yourself wanting to
add a keyword list here, push the routing decision into the LLM
classifier instead.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .context_routing import RouteDecision

logger = logging.getLogger(__name__)


_RETRY_KEYWORDS = (
    "再查",
    "再试",
    "重试",
    "再来一次",
    "再来一遍",
    "retry",
    "again",
)


class ContextDeciderFallbackMixin:
    """Fallback tool selection used when LLM routing fails."""

    max_tools: int
    tool_registry: Any

    def _default_orchestration_strategy(self, tools: list[str] | None = None, user_lower: str = "") -> dict[str, Any]: ...

    def _rule_based_fallback(
        self,
        user_message: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RouteDecision:
        """Conservative fallback when the LLM router cannot answer.

        Two structural cases are handled here because they can be decided
        from durable context state with very low false-positive risk:

        - ``recent_tool_errors`` + a retry phrase → retry the last failed
          tool. The keyword list is intentionally small ("retry / 重试 /
          再试 / 再来一次"). It is paired with a hard structural guard
          (a recent error must exist) so it cannot misfire on prose.
        - ``recent_tool_state`` + ``trace_query`` available → surface
          the persisted trace so the user can ask follow-up questions
          about an already-executed tool call.

        Anything else falls through to ``chat`` with no tools. Older
        revisions of this module attempted keyword-based tool selection
        for files / web / bash / skills; that path is gone because it
        was the largest source of misrouting and was tracked as the H1
        whack-a-mole rule finding.

        Phase B: returns RouteDecision instead of ContextDecision.
        """
        user_lower = user_message.lower()
        available_tools = self.tool_registry.list_tools()

        if any(kw in user_lower for kw in _RETRY_KEYWORDS) and context:
            recent_tool_errors = context.get("recent_tool_errors")
            if isinstance(recent_tool_errors, list) and recent_tool_errors:
                last_tool = str(recent_tool_errors[0].get("tool_name", "")).strip()
                if last_tool and last_tool in available_tools:
                    logger.info(
                        "[ContextDecider] Retry fallback matched last failed tool: %s",
                        last_tool,
                    )
                    return RouteDecision(
                        profile="chat",
                        graph_shape="tool_loop",
                        complexity="simple",
                        tools=[last_tool],
                        reasoning=(
                            "Retry request detected, reusing last failed tool: "
                            f"{last_tool}"
                        ),
                    )

        if "trace_query" in available_tools and context:
            recent_tool_state = context.get("recent_tool_state")
            if isinstance(recent_tool_state, list) and recent_tool_state:
                logger.info(
                    "[ContextDecider] Trace fallback matched recent tool state"
                )
                return RouteDecision(
                    profile="chat",
                    graph_shape="tool_loop",
                    complexity="simple",
                    tools=["trace_query"],
                    reasoning=(
                        "LLM router unavailable; recent tool execution state "
                        "exists, surfacing trace_query so the user can ask "
                        "follow-up questions about the last tool call."
                    ),
                )

        logger.info("[ContextDecider] Rule-based fallback returned conservative chat intent")
        return RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            reasoning=(
                "LLM router unavailable and no structural retry/trace context "
                "to act on; defaulting to chat with no tools."
            ),
        )


__all__ = ["ContextDeciderFallbackMixin"]
