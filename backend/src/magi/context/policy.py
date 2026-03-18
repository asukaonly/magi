"""Policy helpers for implicit prompt-context retrieval."""

from __future__ import annotations

from .contracts import ContextPolicyDecision

PROCEDURAL_TASK_CATEGORIES = {"code_execution", "file_operation", "planning"}
PROCEDURAL_HINTS = (
    "as usual",
    "same as before",
    "usual workflow",
    "usual flow",
    "按之前",
    "之前那套",
    "按惯例",
    "像之前一样",
    "按以前",
)


class ContextPolicy:
    """Decide whether implicit memory retrieval should run for a prompt build."""

    def decide(
        self,
        *,
        user_message: str,
        task_category: str,
    ) -> ContextPolicyDecision:
        query = str(user_message or "").strip() or str(task_category or "").strip()
        allowed_layers: tuple[str, ...] = ("L0",)
        lowered = query.lower()
        if task_category in PROCEDURAL_TASK_CATEGORIES and any(hint in lowered for hint in PROCEDURAL_HINTS):
            allowed_layers = ("L0", "L4")
        return ContextPolicyDecision(
            retrieve_implicit_memory=bool(query),
            retrieval_query=query or None,
            allowed_layers=allowed_layers,
        )
