"""Small routing helpers for hybrid retrieval."""

from __future__ import annotations

from ..context_scope.models import normalize_context_resolution_signals
from .mode_registry import VALID_MODES
from .models import RetrievalQuery

# Legacy query_mode names → new unified modes.
_LEGACY_MODE_MAP: dict[str, str] = {
    "detail": "exact_fact",
    "experience": "strategy",
    "graph": "exact_fact",
}


def normalize_query_mode(query_mode: str | None) -> str | None:
    """Normalize retrieval mode names into the supported set.

    Returns None when no hint is provided, letting the IntentDecider
    route purely from the query text.
    """
    if not query_mode:
        return None
    query_mode = query_mode.strip().lower()
    if query_mode in VALID_MODES:
        return query_mode
    mapped = _LEGACY_MODE_MAP.get(query_mode)
    if mapped:
        return mapped
    return None


def build_query(**kwargs) -> RetrievalQuery:
    """Build a RetrievalQuery with a normalized query mode."""
    kwargs["query_mode"] = normalize_query_mode(kwargs.get("query_mode"))
    kwargs["context_signals"] = normalize_context_resolution_signals(kwargs.get("context_signals"))
    return RetrievalQuery(**kwargs)
