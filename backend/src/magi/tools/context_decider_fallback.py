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
        available_tools = self.tool_registry.list_tools()

        retry_decision = self._retry_fallback_decision(
            user_message,
            context,
            available_tools,
        )
        if retry_decision is not None:
            return retry_decision

        trace_decision = self._trace_fallback_decision(context, available_tools)
        if trace_decision is not None:
            return trace_decision

        return self._conservative_chat_decision()

    def _retry_fallback_decision(
        self,
        user_message: str,
        context: Optional[dict[str, Any]],
        available_tools: list[str],
    ) -> RouteDecision | None:
        if not context or not self._is_retry_request(user_message):
            return None
        last_tool = self._last_failed_tool(context)
        if not last_tool or last_tool not in available_tools:
            return None

        logger.info(
            "[ContextDecider] Retry fallback matched last failed tool: %s",
            last_tool,
        )
        return RouteDecision(
            profile="chat",
            graph_shape="tool_loop",
            complexity="simple",
            tools=[last_tool],
            reasoning=f"Retry request detected, reusing last failed tool: {last_tool}",
        )

    @staticmethod
    def _is_retry_request(user_message: str) -> bool:
        user_lower = user_message.lower()
        return any(kw in user_lower for kw in _RETRY_KEYWORDS)

    @staticmethod
    def _last_failed_tool(context: dict[str, Any]) -> str:
        recent_tool_errors = context.get("recent_tool_errors")
        if not isinstance(recent_tool_errors, list) or not recent_tool_errors:
            return ""
        return str(recent_tool_errors[0].get("tool_name", "")).strip()

    def _trace_fallback_decision(
        self,
        context: Optional[dict[str, Any]],
        available_tools: list[str],
    ) -> RouteDecision | None:
        if "trace_query" not in available_tools or not context:
            return None
        if not self._has_recent_tool_state(context):
            return None

        logger.info("[ContextDecider] Trace fallback matched recent tool state")
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

    @staticmethod
    def _has_recent_tool_state(context: dict[str, Any]) -> bool:
        recent_tool_state = context.get("recent_tool_state")
        return isinstance(recent_tool_state, list) and bool(recent_tool_state)

    @staticmethod
    def _conservative_chat_decision() -> RouteDecision:
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
