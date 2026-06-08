"""Lazy in-process cache of predicate-label embeddings for semantic resolution.

Embeds each match-pool predicate's ``embedding_text`` once (per embedding model
identity) so the predicate resolver can cosine-match a query's relation_intent
against the predicate vocabulary. ~30 predicates → one batch embed.
"""

from __future__ import annotations

import logging
from typing import Any

from ..l2.predicate_catalog import ALL_SPECS, get_spec

logger = logging.getLogger(__name__)

# cache_key -> {canonical: vector}
_CACHE: dict[str, dict[str, list[float]]] = {}


def match_pool_canonicals() -> list[str]:
    """Predicates eligible for hop1 user→object resolution (person-subject)."""
    return [s.canonical for s in ALL_SPECS if "person" in s.subject_types]


def reset_predicate_label_cache() -> None:
    """Test hook: clear the in-process cache."""
    _CACHE.clear()


async def get_predicate_label_embeddings(embedding_service: Any) -> dict[str, list[float]]:
    """Return {canonical: vector} for match-pool predicates, building lazily.

    Cached per embedding-model identity (rebuilt only after reset). Returns {} on
    failure so the resolver degrades to the keyword/family path.
    """
    cache_key = getattr(embedding_service, "model_identity", None) or "default"
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    canonicals = match_pool_canonicals()
    texts = [
        (get_spec(c).embedding_text or get_spec(c).natural_labels.get("en", c))
        for c in canonicals
    ]
    try:
        results = await embedding_service.embed_texts(texts)
    except Exception:
        logger.warning("Predicate label embedding failed", exc_info=True)
        return {}

    vectors: dict[str, list[float]] = {}
    for canonical, result in zip(canonicals, results):
        if result is not None and getattr(result, "vector", None):
            vectors[canonical] = list(result.vector)
    _CACHE[cache_key] = vectors
    return vectors


__all__ = [
    "match_pool_canonicals",
    "get_predicate_label_embeddings",
    "reset_predicate_label_cache",
]
