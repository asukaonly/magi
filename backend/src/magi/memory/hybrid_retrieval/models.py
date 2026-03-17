"""Contracts for hybrid memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# RetrievalQuery / RetrievalPayload  (existing contracts, extended)
# ---------------------------------------------------------------------------


@dataclass
class RetrievalQuery:
    """Query contract for memory retrieval."""

    query: str
    user_id: Optional[str]
    session_id: Optional[str]
    time_range: Dict[str, Any]
    query_mode: Optional[str] = None  # optional hint; None = IntentDecider auto-routes
    source_filters: List[str] = field(default_factory=list)
    domain_filters: List[str] = field(default_factory=list)
    limit: int = 10


@dataclass
class RetrievalPayload:
    """Prompt-consumable retrieval result."""

    l0_workbench: List[Dict[str, Any]] = field(default_factory=list)
    l1_events: List[Dict[str, Any]] = field(default_factory=list)
    l2_entity_cards: List[Dict[str, Any]] = field(default_factory=list)
    l2_relationships: List[Dict[str, Any]] = field(default_factory=list)
    l3_reflections: List[Dict[str, Any]] = field(default_factory=list)
    l4_procedures: List[Dict[str, Any]] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# IntentDecider contracts
# ---------------------------------------------------------------------------


@dataclass
class IntentDeciderInput:
    """Input to the intent decider."""

    query: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    raw_time_range: Optional[Dict[str, Any]] = None
    source_filters: List[str] = field(default_factory=list)
    domain_filters: List[str] = field(default_factory=list)
    query_mode_hint: Optional[str] = None  # from RetrievalQuery.query_mode


@dataclass
class TimeRange:
    """Normalized time range (unix timestamps)."""

    start: Optional[float] = None
    end: Optional[float] = None


@dataclass
class L1Conditions:
    """L1 query conditions: BM25 + vector + keyword."""

    content_query: str = ""
    event_types: Optional[List[str]] = None
    source_filters: Optional[List[str]] = None
    domain_filters: Optional[List[str]] = None
    importance_min: Optional[float] = None
    limit: int = 10


@dataclass
class L2Conditions:
    """L2 query conditions: knowledge graph & ToM."""

    entities: Optional[List[str]] = None
    entity_types: Optional[List[str]] = None
    predicates: Optional[List[str]] = None
    include_tom_snapshot: bool = True
    include_relationships: bool = True
    limit: int = 20


@dataclass
class L3Conditions:
    """L3 query conditions: reflection summaries."""

    content_query: str = ""
    summary_types: Optional[List[str]] = None
    limit: int = 5


@dataclass
class L4Conditions:
    """L4 query conditions: procedural memory."""

    content_query: str = ""
    skill_categories: Optional[List[str]] = None
    limit: int = 5


LayerConditions = L1Conditions | L2Conditions | L3Conditions | L4Conditions


@dataclass
class LayerQueryPlan:
    """Query plan for a single memory layer."""

    layer: Literal["L1", "L2", "L3", "L4"]
    conditions: LayerConditions
    time_range: Optional[TimeRange] = None
    is_fallback: bool = False


@dataclass
class IntentDecision:
    """Complete decision from the intent decider."""

    plans: List[LayerQueryPlan] = field(default_factory=list)
    time_range: Optional[TimeRange] = None  # always from rule layer
    reasoning: Optional[str] = None
    source: str = "llm"  # "llm" | "rule_fallback"


# ---------------------------------------------------------------------------
# Retrieval configuration
# ---------------------------------------------------------------------------


@dataclass
class RetrievalConfig:
    """Configuration for hybrid retrieval behavior."""

    # IntentDecider
    intent_decider_llm_enabled: bool = True
    intent_decider_llm_timeout_seconds: float = 3.0
    intent_decider_fallback_on_error: bool = True
    intent_shadow_eval_enabled: bool = True

    # BM25 / FTS5
    fts5_enabled: bool = True

    # RRF
    rrf_k: int = 60
    rrf_weight_bm25: float = 1.0
    rrf_weight_vector: float = 1.0
    rrf_weight_keyword: float = 0.5

    # ResultFusion
    default_max_tokens: int = 8192
    fallback_trigger_threshold: int = 1  # result count < N triggers fallback

    # Vector search filtering
    vector_max_distance: float = 0.7  # cosine distance cap (1 - similarity)

    # Token estimation
    token_estimator: Literal["char_ratio"] = "char_ratio"
    char_per_token_ratio: float = 3.0


