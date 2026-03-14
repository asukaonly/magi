"""Small routing helpers for hybrid retrieval."""

from __future__ import annotations

from .models import RetrievalQuery


def normalize_query_mode(query_mode: str | None) -> str:
    """Normalize retrieval mode names into the supported set."""
    if not query_mode:
        return "detail"
    query_mode = query_mode.strip().lower()
    if query_mode in {"detail", "summary", "experience", "graph", "strategy"}:
        return query_mode
    return "detail"


def build_query(**kwargs) -> RetrievalQuery:
    """Build a RetrievalQuery with a normalized mode."""
    kwargs["query_mode"] = normalize_query_mode(kwargs.get("query_mode"))
    return RetrievalQuery(**kwargs)

