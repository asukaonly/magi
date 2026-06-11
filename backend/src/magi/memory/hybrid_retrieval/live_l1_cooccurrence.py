"""Live L1 co-occurrence fallback (RFC #65 P4).

Last-resort recall: when the structured channel (hop1 hard + P2 soft + P3 hop2)
returns nothing, surface the user's raw L1 co-occurrence neighborhood as
LOW-confidence synthetic soft edges. These reuse P2's soft-edge fusion path
(``is_soft_edge`` -> confidence x SOFT_EDGE_WEIGHT), ranking below any real edge.
NOT query-specific - a "something rather than nothing" grab bag. Never raises.
"""

from __future__ import annotations

import logging
from typing import Any

from .soft_edges import SEMANTIC_EDGE_FACT_KIND, SEMANTIC_EDGE_PREDICATE

logger = logging.getLogger(__name__)

MAX_LIVE_L1 = 10
LIVE_L1_CONFIDENCE = 0.3  # < materialized soft edges (cosine >= 0.75)


async def live_l1_cooccurrence_edges(
    seed_ids: list[str],
    l1_store: Any,
    *,
    limit: int = MAX_LIVE_L1,
) -> list[dict[str, Any]]:
    """User's L1 co-occurrence neighborhood as low-confidence synthetic soft edges."""
    if not seed_ids or l1_store is None:
        return []
    try:
        event_map = await l1_store.get_entity_event_ids(seed_ids)
        event_ids = [eid for ids in event_map.values() for eid in ids]
        if not event_ids:
            return []
        entity_map = await l1_store.get_event_entity_ids(event_ids)
    except Exception:
        logger.warning("live L1 co-occurrence failed", exc_info=True)
        return []

    seeds = set(seed_ids)
    freq: dict[str, int] = {}
    for ids in entity_map.values():
        for ent in ids:
            if ent and ent not in seeds:
                freq[ent] = freq.get(ent, 0) + 1
    top = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:limit]

    seed = seed_ids[0]
    edges: list[dict[str, Any]] = []
    for ent, _count in top:
        edges.append({
            "triple_id": f"livel1:{seed}:{ent}",
            "subject_id": seed,
            "subject_type": "person",
            "predicate": SEMANTIC_EDGE_PREDICATE,
            "object_id": ent,
            "object_type": "",
            "fact_kind": SEMANTIC_EDGE_FACT_KIND,
            "confidence": LIVE_L1_CONFIDENCE,
            "status": "active",
            "_channel": "live_l1",
        })
    return edges


__all__ = ["live_l1_cooccurrence_edges", "MAX_LIVE_L1", "LIVE_L1_CONFIDENCE"]
