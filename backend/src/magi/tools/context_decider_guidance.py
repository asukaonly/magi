"""Routing guardrail and memory guidance helpers for ContextDecider."""

from __future__ import annotations

from typing import Any, Optional

from .context_routing import (
    ContextDecision,
    MemoryGuidance,
    apply_memory_guidance,
    default_orchestration_strategy,
    evaluate_memory_need,
    is_complex_research_request,
    needs_fetch_for_request,
    normalize_orchestration_strategy,
)


class ContextDeciderGuidanceMixin:
    """Apply routing guardrails, memory guidance, and strategy normalization."""

    max_tools: int

    def _apply_memory_guidance(
        self,
        *,
        user_message: str,
        context: Optional[dict[str, Any]],
        decision: ContextDecision,
        available_tools: list[dict[str, Any]],
    ) -> ContextDecision:
        return apply_memory_guidance(
            user_message=user_message,
            context=context,
            decision=decision,
            available_tools=available_tools,
            max_tools=self.max_tools,
        )

    def _default_orchestration_strategy(
        self,
        tools: Optional[list[str]] = None,
        user_lower: str = "",
    ) -> dict[str, Any]:
        return default_orchestration_strategy(tools, user_lower)

    def _is_complex_research_request(self, user_lower: str) -> bool:
        return is_complex_research_request(user_lower)

    def _needs_fetch_for_request(self, user_lower: str) -> bool:
        return needs_fetch_for_request(user_lower)

    def _normalize_orchestration_strategy(self, payload: Any) -> dict[str, Any]:
        return normalize_orchestration_strategy(payload)

    def evaluate_memory_need(
        self,
        user_message: str,
        context: dict
    ) -> Optional[MemoryGuidance]:
        """Evaluate whether memory retrieval would help answer the user's query.

        Returns a boolean recommendation only. The core chat LLM is the
        single decision point for the ``memory_query`` tool's parameters
        (``query_mode``, ``time_range``, ``sources``, ``summary_categories``)
        — the schema description tells it how. No pre-call parameter
        injection is performed here, so the chat LLM is not biased by
        rule-based guesses that historically misrouted queries like
        "我最近在用 chrome 看什么".

        Args:
            user_message: User's message.
            context: Current context (unused; kept for signature stability).

        Returns:
            MemoryGuidance(recommended=True, route="explicit_query") when
            the message looks like a recall / preference / activity-recap
            request; otherwise ``None``.
        """
        return evaluate_memory_need(user_message, context)


__all__ = ["ContextDeciderGuidanceMixin"]
