"""Routing guardrail and memory guidance helpers for ContextDecider."""

from __future__ import annotations

from typing import Any, Optional

from .context_routing import (
    MemoryGuidance,
    RouteDecision,
    apply_memory_guidance,
    evaluate_memory_need,
    is_complex_research_request,
    needs_fetch_for_request,
)


class ContextDeciderGuidanceMixin:
    """Apply routing guardrails, memory guidance, and strategy normalization."""

    max_tools: int

    def _apply_memory_guidance(
        self,
        *,
        user_message: str,
        context: Optional[dict[str, Any]],
        decision: RouteDecision,
        available_tools: list[dict[str, Any]],
    ) -> RouteDecision:
        return apply_memory_guidance(
            user_message=user_message,
            context=context,
            decision=decision,
            available_tools=available_tools,
            max_tools=self.max_tools,
            task_category=decision.profile,
        )

    def _is_complex_research_request(self, user_lower: str) -> bool:
        return is_complex_research_request(user_lower)

    def _needs_fetch_for_request(self, user_lower: str) -> bool:
        return needs_fetch_for_request(user_lower)

    def evaluate_memory_need(
        self,
        user_message: str,
        context: dict
    ) -> Optional[MemoryGuidance]:
        """Evaluate whether memory retrieval would help answer the user's query.

        Returns a boolean recommendation only. The core chat LLM is the
        single decision point for the ``memory_query`` tool's parameters
        (``query_mode``, ``time_range``, ``summary_categories``)
        — the schema description tells it how. No pre-call parameter
        injection is performed here, so the chat LLM is not biased by
        rule-based guesses that historically misrouted queries like
        "我最近在用 chrome 看什么".

        ``sources`` used to be exposed to the LLM here too; it was
        removed because the LLM has no reliable way to map natural-
        language hints to actual source identifiers (the documented
        examples didn't even match the real plugin-emitted values).
        Source narrowing now happens only via internal programmatic
        callers that set RetrievalQuery.source_filters directly.

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
