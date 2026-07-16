"""Contracts for hybrid memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from ..context_scope.models import ContextResolutionSignals


# ---------------------------------------------------------------------------
# RetrievalQuery / RetrievalPayload  (existing contracts, extended)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationTurn:
    """A single turn from the chat history, used to anchor indexical references."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: float  # unix seconds


@dataclass
class RetrievalQuery:
    """Query contract for memory retrieval."""

    query: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    time_range: Dict[str, Any] = field(default_factory=dict)
    query_mode: Optional[str] = None  # unified mode; None = auto-detect
    source_filters: List[str] = field(default_factory=list)
    domain_filters: List[str] = field(default_factory=list)
    summary_categories: List[str] = field(default_factory=list)
    # Resolved product context used by correction-scoped L2 claims. Empty
    # means global context and must never match a scoped refinement.
    context_scope: Dict[str, Any] = field(default_factory=dict)
    # Trusted local signals resolved by HybridRetrievalService at its single
    # entry point. Callers do not turn these values into identities themselves.
    context_signals: ContextResolutionSignals | None = None
    limit: int = 10
    # Original user message text for the current turn. Used by echo filtering
    # so the L1 event of the just-typed user message is suppressed even when
    # the LLM rephrases ``query``. Empty/None disables the extra filter.
    exclude_user_text: Optional[str] = None
    # Recent chat history used to resolve indexical references ("that game",
    # "the one we talked about"). None means no context available.
    conversation_context: Optional[list[ConversationTurn]] = None


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
    # P3 episodic + state retrieval fields
    l2_episodes: List[Dict[str, Any]] = field(default_factory=list)
    l2_experiences: List[Dict[str, Any]] = field(default_factory=list)
    l2_state_facts: List[Dict[str, Any]] = field(default_factory=list)
    l2_state_history: List[Dict[str, Any]] = field(default_factory=list)
    structured_results: List[Dict[str, Any]] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoricalRecallPayload:
    """Answer-facing historical recall payload for upper layers."""

    status: Literal["found", "not_found", "ambiguous", "conflicted"]
    query_mode: Optional[str]
    summary: str
    findings: List[Dict[str, Any]] = field(default_factory=list)
    entity_refs: List[Dict[str, Any]] = field(default_factory=list)
    asset_refs: List[Dict[str, Any]] = field(default_factory=list)
    insufficient_evidence: bool = False
    answering_hints: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)
    structured_results: List[Dict[str, Any]] = field(default_factory=list)


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
    summary_categories: List[str] = field(default_factory=list)
    context_scope: Dict[str, Any] = field(default_factory=dict)
    query_mode_hint: Optional[str] = None  # from RetrievalQuery.query_mode
    l1_limit: int = 10  # per-plan L1 event limit, forwarded from request


@dataclass
class TimeRange:
    """Normalized time range (unix timestamps)."""

    start: Optional[float] = None
    end: Optional[float] = None
    as_of: Optional[float] = None


@dataclass
class TemporalContext:
    """Explicit temporal intent for L2 retrieval queries."""

    mode: Literal["none", "current", "as_of", "during", "since", "before", "after"] = "none"
    start: Optional[float] = None
    end: Optional[float] = None
    anchor: Optional[float] = None
    confidence: float = 0.5


@dataclass
class L1Conditions:
    """L1 query conditions: BM25 + vector + keyword."""

    content_query: str = ""
    event_types: Optional[List[str]] = None
    source_filters: Optional[List[str]] = None
    domain_filters: Optional[List[str]] = None
    context_scope: Dict[str, Any] = field(default_factory=dict)
    importance_min: Optional[float] = None
    limit: int = 10


@dataclass
class L2Conditions:
    """L2 query conditions: knowledge graph & ToM."""

    content_query: str = ""
    entities: Optional[List[str]] = None
    subject_hint: Optional[str] = None
    predicate_family: Optional[str] = None
    relation_intent: Optional[str] = (
        None  # English relation phrase from LLM, for embedding predicate resolution (RFC #65 P1)
    )
    predicate_source: Optional[str] = (
        None  # "explicit"|"embedding"|"llm_family"|"keyword_fallback" (RFC #65 P1)
    )
    allowed_evidence_classes: Optional[set[str]] = None
    evidence_focus_source: Optional[str] = (
        None  # "llm" | "rule_heuristic" | "family_fallback" | None
    )
    entity_types: Optional[List[str]] = None
    predicates: Optional[List[str]] = None
    trait_families: Optional[List[str]] = None
    include_tom_snapshot: bool = True
    include_relationships: bool = True
    include_assertions: bool = True
    include_episodes: bool = False
    include_experiences: bool = False
    relation_direction: Optional[str] = None
    hop_count: int = 1
    status_filter: Optional[List[str]] = None
    context_scope: Dict[str, Any] = field(default_factory=dict)
    semantic_frame: Optional["L2SemanticFrame"] = None
    allow_soft_edges: bool = True  # permit SEMANTIC_CONTEXT soft-edge sparse fallback (RFC #65 P2)
    hop2_target_type: Optional[str] = (
        None  # FINAL answer entity type for 2-hop queries (RFC #65 P3)
    )
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
    subject_scope: Literal["self", "explicit", "multi", "none"]
    answer_kind: Literal["creator", "place", "topic", "person", "software", "media", "unknown"]
    answer_unit: Literal["identity", "presence", "place", "topic", "mixed"] = "mixed"
    subject_mode: Literal["self", "single", "multi", "none"] = "none"
    relation_shape: Literal[
        "single_fact",
        "shared_fact",
        "between_people",
        "comparison",
        "two_hop",
        "unknown",
    ] = "unknown"
    subject_mentions: List[str] = field(default_factory=list)
    object_mentions: List[str] = field(default_factory=list)
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
    intent_decider_llm_timeout_seconds: float = 10.0
    intent_shadow_eval_enabled: bool = True

    # Post-retrieval grounding filter (LLM-as-listwise-relevance-filter).
    # Trims raw candidate set so the answer LLM doesn't waste tokens /
    # attention on noise. Only skipped for trivial 0/1-candidate sets
    # (see MIN_CANDIDATES_TO_FILTER in grounding_filter.py).
    grounding_filter_enabled: bool = True
    grounding_filter_timeout_seconds: float = 3.0

    # RRF
    rrf_k: int = 60
    rrf_over_fetch_multiplier: int = 5
    rrf_over_fetch_minimum: int = 20
    rrf_weight_bm25: float = 1.0
    rrf_weight_vector: float = 1.0
    rrf_weight_keyword: float = 0.5
    rrf_weight_entity: float = 0.7
    reranker_top_k: int = 20
    reranker_layers: tuple[str, ...] = ("L1", "L3", "L4")
    reranker_candidate_max_chars: int = 500

    # Cross-encoder reranking (optional, on top of heuristic)
    cross_encoder_enabled: bool = False
    cross_encoder_model_id: str | None = None
    cross_encoder_variant: str | None = None

    # Query expansion (LLM-based alternative query generation)
    query_expansion_enabled: bool = True
    query_expansion_timeout_seconds: float = 3.0
    query_expansion_max_expansions: int = 2

    # Graph spreading activation (L2 knowledge graph BFS)
    graph_spreading_enabled: bool = False
    graph_spreading_max_hops: int = 2
    graph_spreading_max_neighbors: int = 10
    graph_spreading_max_entities: int = 50
    graph_spreading_decay: float = 0.5
    rrf_weight_graph: float = 0.6
    rrf_weight_temporal_bm25: float = 0.8

    # Evidence bundle filtering
    evidence_bundle_max_count: int = 8
    evidence_bundle_min_score: float = 0.15

    # Confidence-aware fallback
    confidence_fallback_enabled: bool = False
    confidence_fallback_min_score: float = 0.3
    confidence_fallback_top_k: int = 5

    # ResultFusion
    default_max_tokens: int = 16384
    fallback_trigger_threshold: int = 1
    l0_max_tokens: int = 512
    l0_budget_ratio: float = 0.5

    # ManifestSelector (cross-layer LLM ranking post-fusion)
    manifest_selector_enabled: bool = False
    manifest_selector_top_k: int = 20
    manifest_selector_max_output: int = 10
    manifest_selector_timeout_seconds: float = 8.0
    manifest_selector_candidate_max_chars: int = 400

    # Token budget ratios (layer share of remaining budget after L0)
    l1_budget_ratio: float = 0.5
    l2_budget_ratio: float = 0.4
    l3_budget_ratio: float = 0.4

    # Token estimation
    char_per_token_ratio: float = 3.0

    # L3 category soft preference (see L3Handler._build_category_booster).
    l3_category_soft_boost: float = 1.8
    l3_category_fetch_k_multiplier: float = 1.5
