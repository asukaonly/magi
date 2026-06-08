"""Embedding-primary predicate resolution (RFC #65 P1).

Runs after the LLM intent decider, before grounding. Embeds the LLM-produced
``relation_intent`` and cosine-matches it against the predicate-label embedding
cache, writing the top-K canonical predicates into ``conditions.predicates`` so
grounding's ``_ground_predicates`` (which prefers ``conditions.predicates``)
carries them into the P0 TraversalPlan. Degrades to the existing
predicate_family / keyword path when there's no confident match.
"""

from __future__ import annotations

import logging
from typing import Any

from ..l2.predicate_catalog import get_spec
from .entity_semantic_builder import cosine_similarity
from .models import L2Conditions
from .predicate_label_embeddings import get_predicate_label_embeddings

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 0.45


def _degrade_source(conditions: L2Conditions) -> str:
    return "llm_family" if conditions.predicate_family else "keyword_fallback"


def _dominant_family(predicates: list[str]) -> str | None:
    """Family of the top-ranked hit (predicates are already cosine-ranked)."""
    for p in predicates:
        spec = get_spec(p)
        if spec is not None:
            return spec.family
    return None


async def resolve_predicates(
    conditions: L2Conditions,
    *,
    embedding_service: Any,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
) -> None:
    """Populate conditions.predicates via embedding match; degrade gracefully.

    Mutates ``conditions`` in place; sets ``predicate_source`` for observability.
    Never raises — embedding failures degrade to the keyword/family path.
    """
    if conditions.predicates:
        conditions.predicate_source = "explicit"
        return

    text = (conditions.relation_intent or "").strip()
    if not text or embedding_service is None:
        conditions.predicate_source = _degrade_source(conditions)
        return

    try:
        qresult = await embedding_service.embed_text(text)
        vectors = await get_predicate_label_embeddings(embedding_service)
        qvec = getattr(qresult, "vector", None)
        if not qvec or not vectors:
            conditions.predicate_source = _degrade_source(conditions)
            return
        ranked = sorted(
            ((p, cosine_similarity(qvec, v)) for p, v in vectors.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        hits = [p for p, score in ranked[:top_k] if score >= threshold]
    except Exception:
        logger.warning("Predicate resolver embedding failed", exc_info=True)
        conditions.predicate_source = _degrade_source(conditions)
        return

    if hits:
        conditions.predicates = hits
        conditions.predicate_family = _dominant_family(hits) or conditions.predicate_family
        conditions.predicate_source = "embedding"
    else:
        conditions.predicate_source = _degrade_source(conditions)


__all__ = ["resolve_predicates"]
