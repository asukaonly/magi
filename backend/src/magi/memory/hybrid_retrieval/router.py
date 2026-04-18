"""Small routing helpers for hybrid retrieval."""

from __future__ import annotations

from .mode_registry import VALID_MODES
from .models import RetrievalQuery

# Legacy recall_intent → query_mode migration map.
_RECALL_INTENT_TO_MODE: dict[str, str] = {
    "event_recall": "episode_recall",
    "preference_recall": "exact_fact",
    "profile_fact_recall": "exact_fact",
    "relationship_recall": "exact_fact",
    "workflow_reuse": "strategy",
}

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
    """Build a RetrievalQuery with a normalized mode.

    Accepts legacy ``recall_intent`` and maps it to ``query_mode``
    when no explicit ``query_mode`` is provided.
    """
    # Migrate legacy recall_intent → query_mode
    recall_intent = kwargs.pop("recall_intent", None)
    if not kwargs.get("query_mode") and recall_intent:
        mapped = _RECALL_INTENT_TO_MODE.get(str(recall_intent).strip().lower())
        if mapped:
            kwargs["query_mode"] = mapped

    kwargs["query_mode"] = normalize_query_mode(kwargs.get("query_mode"))
    return RetrievalQuery(**kwargs)
