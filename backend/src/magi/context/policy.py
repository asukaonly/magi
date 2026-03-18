"""Policy helpers for implicit prompt-context retrieval."""

from __future__ import annotations

from .contracts import ContextPolicyDecision


class ContextPolicy:
    """Decide whether implicit memory retrieval should run for a prompt build."""

    def decide(
        self,
        *,
        user_message: str,
        task_category: str,
    ) -> ContextPolicyDecision:
        query = str(user_message or "").strip() or str(task_category or "").strip()
        return ContextPolicyDecision(
            retrieve_implicit_memory=bool(query),
            retrieval_query=query or None,
        )
