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
    recall_intent: Optional[str] = None
    query_mode: Optional[str] = None  # optional hint; None = IntentDecider auto-routes
    source_filters: List[str] = field(default_factory=list)
    domain_filters: List[str] = field(default_factory=list)
    limit: int = 10


@dataclass
class RetrievalPayload:
    """Prompt-consumable retrieval result."""

    l0_workbench: List[Dict[str, Any]] = field(default_factory=list)
    l1_events: List[Dict[str, Any]] = field(default_factory=list)
    l1_evidence_bundles: List[Dict[str, Any]] = field(default_factory=list)
    l1_timeline_summary: List[Dict[str, Any]] = field(default_factory=list)
    l2_entity_cards: List[Dict[str, Any]] = field(default_factory=list)
    l2_relationships: List[Dict[str, Any]] = field(default_factory=list)
    l2_assertions: List[Dict[str, Any]] = field(default_factory=list)
    l3_reflections: List[Dict[str, Any]] = field(default_factory=list)
    l4_procedures: List[Dict[str, Any]] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoricalRecallPayload:
    """Answer-facing historical recall payload for upper layers."""

    status: Literal["found", "not_found", "ambiguous", "conflicted"]
    recall_intent: Optional[str]
    query_mode: Optional[str]
    summary: str
    findings: List[Dict[str, Any]] = field(default_factory=list)
    insufficient_evidence: bool = False
    answering_hints: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)


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
    recall_intent_hint: Optional[str] = None
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

    content_query: str = ""
    entities: Optional[List[str]] = None
    subject_hint: Optional[str] = None
    predicate_family: Optional[str] = None
    entity_types: Optional[List[str]] = None
    predicates: Optional[List[str]] = None
    trait_families: Optional[List[str]] = None
    include_tom_snapshot: bool = True
    include_relationships: bool = True
    include_assertions: bool = True
    relation_direction: Optional[str] = None
    hop_count: int = 1
    status_filter: Optional[List[str]] = None
    semantic_frame: Optional["L2SemanticFrame"] = None
    limit: int = 20


@dataclass
class SemanticConstraint:
    """Structured query constraint for L2 semantic planning."""

    scope: Literal["target", "interaction"]
    facet: Literal["platform", "located_in", "category"]
    raw_value: str
    resolved_entity_id: Optional[str] = None
    resolved_facet_value: Optional[str] = None


@dataclass
class L2SemanticFrame:
    """Structured semantic frame used for L2 query planning."""

    query_family: Literal["affinity", "relationship", "profile", "activity", "lookup"]
    subject_scope: Literal["self", "explicit", "none"]
    answer_kind: Literal["creator", "place", "topic", "person", "software", "unknown"]
    answer_unit: Literal["identity", "presence", "place", "topic", "mixed"]
    answer_shape: Literal["list", "single", "boolean"]
    polarity: Literal["positive", "negative", "neutral", "any"]
    entity_mentions: List[str] = field(default_factory=list)
    constraints: List[SemanticConstraint] = field(default_factory=list)
    ranking_mode: Literal["affinity", "confidence", "recency"] = "affinity"


@dataclass
class L3Conditions:
    """L3 query conditions: reflection summaries."""

    content_query: str = ""
    summary_types: Optional[List[str]] = None
    summary_categories: Optional[List[str]] = None
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
    reranker_enabled: bool = True
    reranker_backend: Literal["noop", "heuristic", "llm"] = "heuristic"
    reranker_mode: Literal["local", "remote"] = "local"
    reranker_top_k: int = 15
    reranker_layers: tuple[str, ...] = ("L1", "L3", "L4")
    reranker_timeout_seconds: float = 0.8
    reranker_candidate_max_chars: int = 500
    reranker_remote_provider_id: str = ""
    reranker_remote_model: str = ""
    reranker_local_model_source: Literal["managed", "external"] = "managed"
    reranker_local_managed_model_id: str | None = None
    reranker_local_model_file_path: str | None = None
    reranker_local_max_context_tokens: int = 2048
    reranker_llm_weight: float = 0.55

    # ResultFusion
    default_max_tokens: int = 8192
    fallback_trigger_threshold: int = 1  # result count < N triggers fallback
    l0_max_tokens: int = 512
    l0_budget_ratio: float = 0.5

    # Vector search filtering
    vector_max_distance: float = 0.7  # cosine distance cap (1 - similarity)

    # Token estimation
    token_estimator: Literal["char_ratio"] = "char_ratio"
    char_per_token_ratio: float = 3.0
