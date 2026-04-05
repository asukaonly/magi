"""Adaptive retrieval parameter tuning based on query intent.

Adjusts RRF weights and top-K values per query mode / recall intent
so that different query types get optimally tuned retrieval behavior
without requiring manual configuration.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from .models import RetrievalConfig


# ---------------------------------------------------------------------------
# Preset overrides per query_mode
# ---------------------------------------------------------------------------

# query_mode → partial RetrievalConfig overrides
_MODE_OVERRIDES: dict[str, dict[str, float | int]] = {
    # Detail / event recall — favor BM25 + vector, reduce entity weight
    "detail": {
        "rrf_weight_bm25": 1.2,
        "rrf_weight_vector": 1.2,
        "rrf_weight_keyword": 0.6,
        "rrf_weight_entity": 0.4,
        "rrf_weight_graph": 0.3,
        "reranker_top_k": 20,
    },
    # Summary recall — broader results, balanced weights
    "summary": {
        "rrf_weight_bm25": 0.8,
        "rrf_weight_vector": 1.0,
        "rrf_weight_keyword": 0.4,
        "rrf_weight_entity": 0.7,
        "rrf_weight_graph": 0.6,
        "reranker_top_k": 10,
    },
    # Graph / relationship queries — boost entity + graph paths
    "graph": {
        "rrf_weight_bm25": 0.6,
        "rrf_weight_vector": 0.8,
        "rrf_weight_keyword": 0.3,
        "rrf_weight_entity": 1.2,
        "rrf_weight_graph": 1.0,
        "reranker_top_k": 15,
    },
    # Experience / strategy — favor L4, moderate L1
    "experience": {
        "rrf_weight_bm25": 0.8,
        "rrf_weight_vector": 1.0,
        "rrf_weight_keyword": 0.4,
        "rrf_weight_entity": 0.6,
        "rrf_weight_graph": 0.5,
    },
    "strategy": {
        "rrf_weight_bm25": 0.7,
        "rrf_weight_vector": 1.0,
        "rrf_weight_keyword": 0.4,
        "rrf_weight_entity": 0.5,
        "rrf_weight_graph": 0.5,
    },
}

# recall_intent → partial overrides (higher priority than mode)
_INTENT_OVERRIDES: dict[str, dict[str, float | int]] = {
    "event_recall": {
        "rrf_weight_bm25": 1.2,
        "rrf_weight_vector": 1.2,
        "rrf_weight_keyword": 0.6,
        "rrf_weight_entity": 0.4,
        "rrf_weight_graph": 0.3,
        "reranker_top_k": 20,
    },
    "preference_recall": {
        "rrf_weight_bm25": 0.7,
        "rrf_weight_vector": 1.0,
        "rrf_weight_keyword": 0.4,
        "rrf_weight_entity": 1.0,
        "rrf_weight_graph": 0.9,
        "reranker_top_k": 15,
    },
    "relationship_recall": {
        "rrf_weight_bm25": 0.5,
        "rrf_weight_vector": 0.8,
        "rrf_weight_keyword": 0.3,
        "rrf_weight_entity": 1.2,
        "rrf_weight_graph": 1.0,
        "reranker_top_k": 15,
    },
    "profile_fact_recall": {
        "rrf_weight_bm25": 0.8,
        "rrf_weight_vector": 1.0,
        "rrf_weight_keyword": 0.5,
        "rrf_weight_entity": 0.8,
        "rrf_weight_graph": 0.7,
    },
    "workflow_reuse": {
        "rrf_weight_bm25": 0.6,
        "rrf_weight_vector": 1.0,
        "rrf_weight_keyword": 0.5,
        "rrf_weight_entity": 0.5,
        "rrf_weight_graph": 0.4,
    },
}


def adapt_config(
    config: RetrievalConfig,
    *,
    query_mode: Optional[str] = None,
    recall_intent: Optional[str] = None,
) -> RetrievalConfig:
    """Return an adapted copy of *config* based on intent signals.

    ``recall_intent`` overrides take priority over ``query_mode``.
    If neither matches any preset, the original config is returned unchanged.
    """
    overrides: dict[str, float | int] = {}

    # Layer 1: mode-based overrides
    if query_mode and query_mode in _MODE_OVERRIDES:
        overrides.update(_MODE_OVERRIDES[query_mode])

    # Layer 2: intent-based overrides (higher priority)
    if recall_intent and recall_intent in _INTENT_OVERRIDES:
        overrides.update(_INTENT_OVERRIDES[recall_intent])

    if not overrides:
        return config

    return replace(config, **overrides)
