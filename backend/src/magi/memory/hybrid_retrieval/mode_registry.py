"""Query mode registry — maps unified query_mode to pipeline configuration.

Each mode controls routing, retrieval, evidence assembly, and answer synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class QueryModePlan:
    """Pipeline configuration for a single query mode."""

    mode: str
    primary_layers: list[str]
    fallback_layers: list[str]
    retrieval_units: list[str]
    rrf_profile: dict[str, float | int]
    evidence_shape: str
    reducer_type: str
    l1_retrieval_scopes: list[str] | None = None
    allow_query_expansion: bool = True
    time_decay_enabled: bool = True
    layer_quota: dict[str, int] | None = None


# layer_quota values are tunable initial values; calibrate against real recall data.
MODE_REGISTRY: dict[str, QueryModePlan] = {
    # Invariant: every mode reaches L1 either via ``primary_layers`` or
    # ``fallback_layers``. L1 holds the raw event stream and is the
    # universal safety net when L2 / L3 / L4 yield nothing — keeping
    # this invariant prevents whole classes of "no recall" failures
    # when the chat LLM picks a narrow ``query_mode``. If you add a
    # new mode here, include L1 in primary or fallback.
    "event_stream": QueryModePlan(
        mode="event_stream",
        primary_layers=["L1"],
        fallback_layers=[],
        retrieval_units=["event"],
        rrf_profile={
            "rrf_weight_bm25": 1.0,
            "rrf_weight_vector": 0.8,
            "rrf_weight_keyword": 0.7,
            "reranker_top_k": 20,
        },
        evidence_shape="passthrough",
        reducer_type="passthrough",
        allow_query_expansion=False,
        time_decay_enabled=True,
        layer_quota={"L1": 20},
    ),
    "exact_fact": QueryModePlan(
        mode="exact_fact",
        primary_layers=["L2"],
        fallback_layers=["L1"],
        retrieval_units=["entity_card", "kg_edge", "facet", "event"],
        rrf_profile={
            "rrf_weight_bm25": 0.8,
            "rrf_weight_vector": 1.0,
            "rrf_weight_entity": 1.2,
            "rrf_weight_graph": 1.0,
            "rrf_weight_keyword": 0.5,
            "reranker_top_k": 20,
        },
        evidence_shape="fact_card",
        reducer_type="span_select",
        l1_retrieval_scopes=["fact_authoritative"],
        allow_query_expansion=True,
        time_decay_enabled=False,
        layer_quota={"L2": 8, "L1": 6, "L3": 2, "L4": 1},
    ),
    "current_state": QueryModePlan(
        mode="current_state",
        primary_layers=["L2"],
        fallback_layers=["L1"],
        retrieval_units=["state_assertion", "snapshot", "event"],
        rrf_profile={
            "rrf_weight_bm25": 0.6,
            "rrf_weight_vector": 0.8,
            "rrf_weight_entity": 1.2,
            "rrf_weight_graph": 0.8,
            "rrf_weight_keyword": 0.4,
            "reranker_top_k": 10,
        },
        evidence_shape="state_card",
        reducer_type="latest_version",
        l1_retrieval_scopes=["fact_authoritative"],
        allow_query_expansion=False,
        time_decay_enabled=False,
        layer_quota={"L2": 6, "L1": 3, "L3": 2, "L4": 1},
    ),
    "episode_recall": QueryModePlan(
        mode="episode_recall",
        primary_layers=["L2", "L1"],
        fallback_layers=["L3"],
        retrieval_units=["episode", "event_cluster", "event"],
        rrf_profile={
            "rrf_weight_bm25": 1.0,
            "rrf_weight_vector": 1.2,
            "rrf_weight_entity": 0.6,
            "rrf_weight_graph": 0.4,
            "rrf_weight_keyword": 0.6,
            "reranker_top_k": 20,
        },
        evidence_shape="episode_bundle",
        reducer_type="narrative",
        allow_query_expansion=True,
        time_decay_enabled=True,
        layer_quota={"L1": 12, "L2": 4, "L3": 2, "L4": 1},
    ),
    "experience_recall": QueryModePlan(
        mode="experience_recall",
        primary_layers=["L2", "L1"],
        fallback_layers=["L3"],
        retrieval_units=["experience", "event"],
        rrf_profile={
            "rrf_weight_bm25": 0.9,
            "rrf_weight_vector": 1.0,
            "rrf_weight_entity": 0.8,
            "rrf_weight_graph": 0.4,
            "rrf_weight_keyword": 0.8,
            "reranker_top_k": 20,
        },
        evidence_shape="episode_bundle",
        reducer_type="narrative",
        allow_query_expansion=True,
        time_decay_enabled=True,
        layer_quota={"L1": 10, "L2": 6, "L3": 2, "L4": 1},
    ),
    "cross_session": QueryModePlan(
        mode="cross_session",
        primary_layers=["L2", "L1"],
        fallback_layers=["L3"],
        retrieval_units=["entity_group", "episode_span", "event"],
        rrf_profile={
            "rrf_weight_bm25": 0.8,
            "rrf_weight_vector": 1.0,
            "rrf_weight_entity": 1.0,
            "rrf_weight_graph": 0.9,
            "rrf_weight_keyword": 0.5,
            "reranker_top_k": 20,
        },
        evidence_shape="grouped_list",
        reducer_type="enumerate",
        allow_query_expansion=True,
        time_decay_enabled=False,
        layer_quota={"L1": 12, "L2": 8, "L3": 3, "L4": 1},
    ),
    "temporal_compare": QueryModePlan(
        mode="temporal_compare",
        primary_layers=["L2", "L1"],
        fallback_layers=["L3"],
        retrieval_units=["state_version", "episode_pair", "time_anchor"],
        rrf_profile={
            "rrf_weight_bm25": 1.0,
            "rrf_weight_vector": 1.0,
            "rrf_weight_entity": 0.8,
            "rrf_weight_graph": 0.6,
            "rrf_weight_keyword": 0.6,
            "reranker_top_k": 20,
        },
        evidence_shape="comparison_frame",
        reducer_type="anchor_compare",
        l1_retrieval_scopes=["fact_authoritative"],
        allow_query_expansion=False,
        time_decay_enabled=False,
        layer_quota={"L2": 6, "L1": 6, "L3": 2, "L4": 1},
    ),
    "summary": QueryModePlan(
        mode="summary",
        primary_layers=["L3"],
        fallback_layers=["L1"],
        retrieval_units=["summary", "event"],
        rrf_profile={
            "rrf_weight_bm25": 0.8,
            "rrf_weight_vector": 1.0,
            "rrf_weight_entity": 0.7,
            "rrf_weight_graph": 0.6,
            "rrf_weight_keyword": 0.4,
            "reranker_top_k": 10,
        },
        evidence_shape="passthrough",
        reducer_type="passthrough",
        l1_retrieval_scopes=["fact_authoritative"],
        allow_query_expansion=True,
        time_decay_enabled=True,
        layer_quota={"L3": 8, "L1": 4, "L2": 2, "L4": 1},
    ),
    "strategy": QueryModePlan(
        mode="strategy",
        primary_layers=["L4"],
        fallback_layers=["L1"],
        retrieval_units=["procedure", "event"],
        rrf_profile={
            "rrf_weight_bm25": 0.7,
            "rrf_weight_vector": 1.0,
            "rrf_weight_entity": 0.5,
            "rrf_weight_graph": 0.5,
            "rrf_weight_keyword": 0.4,
        },
        evidence_shape="passthrough",
        reducer_type="passthrough",
        l1_retrieval_scopes=["fact_authoritative"],
        allow_query_expansion=True,
        time_decay_enabled=False,
        layer_quota={"L4": 8, "L1": 3, "L2": 2, "L3": 1},
    ),
    "activity_summary": QueryModePlan(
        mode="activity_summary",
        primary_layers=["L3"],
        fallback_layers=["L1"],
        retrieval_units=["summary", "event"],
        rrf_profile={
            "rrf_weight_bm25": 0.7,
            "rrf_weight_vector": 0.9,
            "rrf_weight_entity": 0.5,
            "rrf_weight_graph": 0.4,
            "rrf_weight_keyword": 0.6,
            "reranker_top_k": 10,
        },
        evidence_shape="activity_digest",
        reducer_type="time_window_aggregate",
        l1_retrieval_scopes=["fact_authoritative"],
        allow_query_expansion=False,
        time_decay_enabled=True,
        layer_quota={"L3": 8, "L1": 4, "L2": 2, "L4": 1},
    ),
}

# All valid mode names for external validation.
VALID_MODES: frozenset[str] = frozenset(MODE_REGISTRY)
