"""Small routing helpers for hybrid retrieval."""

from __future__ import annotations

from .models import RetrievalQuery


def normalize_recall_intent(recall_intent: str | None) -> str | None:
    """Normalize retrieval recall intent names into the supported set."""
    if not recall_intent:
        return None
    recall_intent = recall_intent.strip().lower()
    if recall_intent in {
        "event_recall",
        "preference_recall",
        "profile_fact_recall",
        "relationship_recall",
        "workflow_reuse",
    }:
        return recall_intent
    return None


def normalize_query_mode(query_mode: str | None) -> str | None:
    """Normalize retrieval mode names into the supported set.

    Returns None when no hint is provided, letting the IntentDecider
    route purely from the query text.
    """
    if not query_mode:
        return None
    query_mode = query_mode.strip().lower()
    if query_mode in {"detail", "summary", "experience", "graph", "strategy"}:
        return query_mode
    return None


def build_query(**kwargs) -> RetrievalQuery:
    """Build a RetrievalQuery with a normalized mode."""
    kwargs["recall_intent"] = normalize_recall_intent(kwargs.get("recall_intent"))
    kwargs["query_mode"] = normalize_query_mode(kwargs.get("query_mode"))
    return RetrievalQuery(**kwargs)
