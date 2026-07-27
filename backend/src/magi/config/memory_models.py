"""Memory and embedding application configuration models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class MemoryBackend(str, Enum):
    """Memory storage backend type."""

    MEMORY = "memory"
    CHROMADB = "chromadb"
    FAISS = "faiss"


class EmbeddingBackend(str, Enum):
    """Embedding vector backend type."""

    SQLITE_VEC = "sqlite_vec"
    OPENAI = "openai"


class EmbeddingMode(str, Enum):
    """Embedding execution mode."""

    OFF = "off"
    REMOTE = "remote"
    LOCAL = "local"


class LocalEmbeddingModelSource(str, Enum):
    """How a local embedding model is referenced."""

    MANAGED = "managed"
    EXTERNAL = "external"


class LocalEmbeddingSettings(BaseModel):
    """Local ONNX embedding model settings."""

    model_source: LocalEmbeddingModelSource = Field(default=LocalEmbeddingModelSource.MANAGED)
    managed_model_id: Optional[str] = Field(default=None)
    model_dir_path: Optional[str] = Field(default=None)
    idle_timeout_seconds: int = Field(default=1800, ge=60)
    variant: Optional[str] = Field(
        default=None,
        description=(
            "Optional ONNX quantization variant override (e.g. 'fp32', 'fp16', "
            "'quantized', 'int8'). When None, the platform default from the "
            "model's registry entry is used."
        ),
    )


class EmbeddingSettings(BaseModel):
    """Embedding configuration. Note: embedding model is configured via LLM EMBEDDING scenario."""

    backend: EmbeddingBackend = Field(default=EmbeddingBackend.SQLITE_VEC)
    mode: EmbeddingMode = Field(default=EmbeddingMode.OFF)
    local: LocalEmbeddingSettings = Field(default_factory=LocalEmbeddingSettings)


class MemoryHistoryBehavior(str, Enum):
    """Retention behavior for historical memory once it ages out of the hot path."""

    DELETE = "delete"
    ARCHIVE = "archive"


class MemoryL0Settings(BaseModel):
    """L0 working-memory settings."""

    enabled: bool = Field(default=True)
    checkpoint_interval_seconds: int = Field(default=30, ge=1)
    attention_update_turn_threshold: int = Field(default=3, ge=1, le=20)
    attention_update_idle_seconds: int = Field(default=30, ge=1, le=300)
    attention_update_max_delay_seconds: int = Field(default=90, ge=1, le=600)

    @model_validator(mode="after")
    def validate_attention_update_delays(self) -> "MemoryL0Settings":
        """Keep the hard update deadline at or beyond the idle deadline."""
        if self.attention_update_max_delay_seconds < self.attention_update_idle_seconds:
            raise ValueError(
                "attention_update_max_delay_seconds must be greater than or equal to "
                "attention_update_idle_seconds"
            )
        return self


class MemoryL1Settings(BaseModel):
    """L1 long-term event memory settings."""

    enabled: bool = Field(default=True)
    retention_days: int = Field(default=30, ge=1)
    t1_importance_enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    maintenance_enabled: bool = Field(
        default=True,
        description="Register periodic L1 retention maintenance with the runtime scheduler.",
    )
    maintenance_interval_seconds: float = Field(
        default=86_400.0,
        ge=300.0,
        description="Interval between L1 retention maintenance runs (seconds). Minimum 300 to avoid excessive load.",
    )


class MemoryL2LifecycleSettings(BaseModel):
    """Tunable thresholds for L2 maintenance decay, archival, and reconciliation.

    These previously lived as hardcoded constants on the L2 maintenance daemon.
    Defaults preserve the prior runtime behavior; surfacing them here keeps all
    memory tuning in the unified ``agent.memory`` config instead of scattered
    module constants.
    """

    fast_decay_ttl_seconds: float = Field(
        default=4 * 3600,
        ge=60,
        description="Expire 'fast_decay' assertions (annoyance/irritation) this long after last update.",
    )
    session_decay_ttl_seconds: float = Field(
        default=24 * 3600,
        ge=60,
        description="Expire 'session_decay' assertions (mood/engagement) this long after last update.",
    )
    archive_confidence_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Knowledge-graph edges below this confidence and past the staleness window are archived.",
    )
    archive_staleness_seconds: float = Field(
        default=90 * 86400,
        ge=3600,
        description="Staleness window before a low-confidence edge is archived (seconds).",
    )
    archive_single_observation_staleness_seconds: float = Field(
        default=180 * 86400,
        ge=3600,
        description="Staleness window before a single-observation edge is archived (seconds).",
    )
    purge_terminal_edge_staleness_seconds: float = Field(
        default=365 * 86400,
        ge=3600,
        description="Hard-delete archived/expired edges older than this (seconds).",
    )
    reconcile_stale_threshold_seconds: float = Field(
        default=3600,
        ge=60,
        description="Reconcile entities whose assertions have not been updated within this window (seconds).",
    )
    reconcile_batch_size: int = Field(
        default=100,
        ge=1,
        description="Number of stale entities reconciled per batch in one maintenance run.",
    )
    reconcile_max_total: int = Field(
        default=500,
        ge=1,
        description="Maximum stale entities reconciled in a single maintenance run.",
    )
    promotion_counter_retention_seconds: float = Field(
        default=30 * 86400,
        ge=3600,
        description="Prune non-promoted promotion-counter keys older than this (seconds).",
    )


class MemoryL2LimitsSettings(BaseModel):
    """Retention/capacity caps for L2 cognition artifacts.

    These previously lived as hardcoded module constants. Defaults preserve the
    prior runtime behavior; the runtime reads them through config-aware accessors
    that fall back to the same defaults when no config is bound.
    """

    snapshot_history_limit: int = Field(
        default=5,
        ge=1,
        description="Max retained entries per ToM snapshot history field (core traits, preferences, relationships).",
    )
    mood_trajectory_limit: int = Field(
        default=20,
        ge=1,
        description="Max retained entries in a ToM snapshot mood/stress/engagement trajectory.",
    )
    max_evidence_event_ids: int = Field(
        default=50,
        ge=1,
        description="Max evidence event IDs retained per knowledge-graph edge, assertion, or facet merge.",
    )


class MemoryL2ConfidenceSettings(BaseModel):
    """Confidence policy for L2 extraction and evidence accumulation.

    These previously lived as inline magic numbers. Defaults preserve the prior
    runtime behavior; the runtime reads them through config-aware accessors that
    fall back to the same defaults when no config is bound.
    """

    accumulation_cap: float = Field(
        default=0.99,
        gt=0.0,
        le=1.0,
        description="Noisy-OR ceiling when accumulating evidence confidence on a graph edge or facet.",
    )
    single_event_cap: float = Field(
        default=0.3,
        gt=0.0,
        le=1.0,
        description="Confidence ceiling for claims/assertions extracted from a single-event batch.",
    )


class MemoryL2EpisodeSettings(BaseModel):
    """Episode formation, promotion, merge, and standout-gate thresholds.

    These previously lived as hardcoded module constants. Defaults preserve the
    prior runtime behavior; the runtime reads them through config-aware accessors
    that fall back to the same defaults when no config is bound.
    """

    min_events_to_promote: int = Field(
        default=3,
        ge=1,
        description="Minimum supporting events before a candidate episode is promoted to active.",
    )
    min_age_to_promote_seconds: float = Field(
        default=30 * 60,
        ge=0,
        description="Minimum candidate age before promotion (seconds).",
    )
    merge_gap_factor: float = Field(
        default=1.5,
        gt=0.0,
        description="Merge adjacent episodes when their gap is below this multiple of the type gap threshold.",
    )
    min_entity_overlap_for_merge: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum primary-entity overlap ratio required to merge adjacent episodes.",
    )
    standout_min_events: int = Field(
        default=8,
        ge=1,
        description="Standout gate: minimum supporting events for a product-grade chapter.",
    )
    standout_min_duration_seconds: float = Field(
        default=45 * 60,
        ge=0,
        description="Standout gate: minimum duration unless the episode is event-dense (seconds).",
    )
    standout_dense_event_count: int = Field(
        default=20,
        ge=1,
        description="Standout gate: event count that qualifies a short episode as dense.",
    )
    standout_min_distinct_entities: int = Field(
        default=2,
        ge=1,
        description="Standout gate: minimum distinct primary entities.",
    )


class MemoryL2ExperienceSettings(BaseModel):
    """Experience promotion gates: quality score, dedup, and repeated-goal seeds.

    These previously lived as hardcoded module constants. Defaults preserve the
    prior runtime behavior; the runtime reads them through config-aware accessors
    that fall back to the same defaults when no config is bound.
    """

    min_quality_score: int = Field(
        default=6,
        ge=1,
        description="Minimum narrative-quality score for a seed to be promoted to an experience.",
    )
    duplicate_overlap_ratio: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        description="Episode-set overlap ratio above which a candidate is treated as a duplicate experience.",
    )
    min_repeated_goal_episodes: int = Field(
        default=3,
        ge=1,
        description="Minimum episodes in a repeated-goal cluster before it can seed an experience.",
    )
    min_repeated_goal_events: int = Field(
        default=8,
        ge=1,
        description="Minimum total source events in a repeated-goal cluster.",
    )
    max_repeated_goal_window_seconds: float = Field(
        default=30 * 24 * 60 * 60,
        ge=0,
        description="Maximum time span of a repeated-goal cluster (seconds).",
    )
    max_repeated_goal_gap_seconds: float = Field(
        default=7 * 24 * 60 * 60,
        ge=0,
        description="Maximum gap between adjacent episodes in a repeated-goal cluster (seconds).",
    )


class MemoryL2AssertionSettings(BaseModel):
    """Assertion confidence curve, graduation gates, and state-family decay TTLs.

    Only the legitimate tuning knobs are surfaced: the evidence->confidence curve,
    the evidence/time gates that graduate an assertion tentative -> corroborated ->
    stable, the state confidence floors/ceilings, and the fast-decay TTLs for
    volatile state families. These previously lived as inline magic numbers;
    defaults preserve prior behavior and the runtime reads them through
    config-aware accessors that fall back when no config is bound.
    """

    confidence_base: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Base confidence for a single-evidence assertion.",
    )
    confidence_slope: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Confidence gained per additional supporting evidence event.",
    )
    confidence_ceiling: float = Field(
        default=0.95,
        gt=0.0,
        le=1.0,
        description="Maximum confidence from the evidence-count curve.",
    )
    stable_evidence_count: int = Field(
        default=3,
        ge=1,
        description="Evidence events required (with the time span) to graduate to stable.",
    )
    stable_time_span_hours: float = Field(
        default=24.0,
        ge=0.0,
        description="Evidence time span (hours) required to graduate to stable.",
    )
    corroborated_evidence_count: int = Field(
        default=2,
        ge=1,
        description="Evidence events required to graduate to corroborated.",
    )
    user_rejected_confidence: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="Confidence assigned to a user-rejected assertion.",
    )
    user_confirmed_confidence_floor: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for a user-confirmed assertion.",
    )
    expired_confidence_ceiling: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Maximum confidence retained by an expired assertion.",
    )
    contradicted_confidence_ceiling: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Maximum confidence retained by a contradicted assertion.",
    )
    stable_confidence_floor: float = Field(
        default=0.82,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for assertions that graduate to stable.",
    )
    temporary_corroborated_confidence_floor: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for temporary-state assertions with one or more evidence events.",
    )
    corroborated_confidence_floor: float = Field(
        default=0.58,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for assertions that graduate to corroborated.",
    )
    tentative_confidence_ceiling: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Maximum confidence retained by tentative assertions.",
    )
    momentary_ttl_seconds: float = Field(
        default=2 * 60 * 60,
        ge=0,
        description="Decay TTL for momentary entity-scoped traits (annoyance/irritation/frustration).",
    )
    mood_ttl_seconds: float = Field(
        default=12 * 60 * 60,
        ge=0,
        description="Decay TTL for mood-family assertions (seconds).",
    )
    stress_ttl_seconds: float = Field(
        default=24 * 60 * 60,
        ge=0,
        description="Decay TTL for stress-family assertions (seconds).",
    )
    engagement_ttl_seconds: float = Field(
        default=12 * 60 * 60,
        ge=0,
        description="Decay TTL for engagement-family assertions (seconds).",
    )
    group_sentiment_ttl_seconds: float = Field(
        default=6 * 60 * 60,
        ge=0,
        description="Decay TTL for group_atmosphere/public_sentiment/relationship_shift assertions (seconds).",
    )


class MemoryL2Settings(BaseModel):
    """L2 structured cognition settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    batch_flush_interval_seconds: int = Field(default=60, ge=30)
    llm_extraction_enabled: bool = Field(default=True)
    auto_extract_relations: bool = Field(default=True)
    conflict_arbitration_enabled: bool = Field(default=True)
    conflict_arbitration_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    maintenance_enabled: bool = Field(
        default=True,
        description="Register periodic L2 entity/graph maintenance with the runtime scheduler.",
    )
    maintenance_interval_seconds: float = Field(
        default=86_400.0,
        ge=300.0,
        description="Interval between L2 maintenance runs (seconds). Minimum 300 to avoid excessive load.",
    )
    consolidation_enabled: bool = Field(
        default=True,
        description="Register periodic L2 episode/experience consolidation with the runtime scheduler.",
    )
    consolidation_interval_seconds: float = Field(
        default=86_400.0,
        ge=300.0,
        description="Interval between L2 episode/experience consolidation runs (seconds). Minimum 300 to avoid excessive load.",
    )
    experience_seed_llm_selection_enabled: bool = Field(
        default=True,
        description="Use the memory summarizer/core model to select coherent experience seed evidence before promotion.",
    )
    experience_seed_llm_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="Timeout for one LLM-backed experience seed selection call.",
    )
    experience_seed_llm_selection_max_per_run: int = Field(
        default=4,
        ge=0,
        description="Maximum LLM-backed experience seed selection calls per automatic consolidation run; extra seeds use local selection.",
    )
    edge_embedding_drain_interval_seconds: float = Field(
        default=5.0,
        ge=1.0,
        description="Idle poll interval (seconds) for the dedicated L2 edge-embedding drain.",
    )
    maintenance_min_mentions: int = Field(
        default=2,
        ge=1,
        description="Orphan prune keeps entities with at least this many resolved mentions (unless referenced in graph).",
    )
    interest_aggregation_enabled: bool = Field(
        default=True,
        description="Run interest aggregation during L2 maintenance to surface INTERESTED_IN edges as inferred preference_profile assertions.",
    )
    interest_observation_threshold: int = Field(
        default=3,
        ge=1,
        description="Minimum INTERESTED_IN edge observation count for a topic to be aggregated into a preference_profile assertion.",
    )
    shadow_conflict_notification_enabled: bool = Field(
        default=True,
        description="Emit a 'profile_conflict' notification for each active shadow assertion that conflicts with a user-authoritative row, prompting the user to resolve the discrepancy.",
    )
    portrait_projection_refresh_delay_seconds: float = Field(
        default=120.0,
        ge=0.0,
        description="Delay before refreshing the product-facing user portrait projection after L2 assertion changes. Multiple changes for the same user are coalesced.",
    )
    derive_schedule_enabled: bool = Field(
        default=True,
        description="Register periodic L2 derived-data (interest aggregation + conflict notifications) task, independent of maintenance.",
    )
    derive_schedule_interval_seconds: float = Field(
        default=21_600.0,
        ge=300.0,
        description="Interval between L2 derive runs (seconds). Minimum 300s.",
    )
    lifecycle: MemoryL2LifecycleSettings = Field(default_factory=MemoryL2LifecycleSettings)
    limits: MemoryL2LimitsSettings = Field(default_factory=MemoryL2LimitsSettings)
    confidence: MemoryL2ConfidenceSettings = Field(default_factory=MemoryL2ConfidenceSettings)
    episode: MemoryL2EpisodeSettings = Field(default_factory=MemoryL2EpisodeSettings)
    experience: MemoryL2ExperienceSettings = Field(default_factory=MemoryL2ExperienceSettings)
    assertion: MemoryL2AssertionSettings = Field(default_factory=MemoryL2AssertionSettings)


class MemoryL3Settings(BaseModel):
    """L3 reflection-memory settings."""

    enabled: bool = Field(default=True)
    retention_days: int = Field(
        default=180,
        ge=1,
        description="Retention window for L3 reflection summaries before retention maintenance may remove unreferenced hot-path summaries.",
    )
    vectors_enabled: bool = Field(default=True)
    llm_summary_enabled: bool = Field(default=True)
    temporal_llm_timeout_seconds: float = Field(default=3.0, ge=0.1)
    temporal_llm_min_event_count: int = Field(default=2, ge=1)
    summary_interval_minutes: int = Field(default=60, ge=1)
    digest_enabled: bool = Field(default=True)
    digest_interval_hours: int = Field(default=24, ge=1)
    maintenance_enabled: bool = Field(
        default=True,
        description="Register periodic L3 summary-retention maintenance with the runtime scheduler.",
    )
    maintenance_interval_seconds: float = Field(
        default=86_400.0,
        ge=300.0,
        description="Interval between L3 summary-retention maintenance runs (seconds). Minimum 300 to avoid excessive load.",
    )


class MemoryL4Settings(BaseModel):
    """L4 procedural-memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    skill_extraction_enabled: bool = Field(default=True)
    strategy_extraction_threshold: int = Field(
        default=5,
        description="Number of new traces before triggering LLM strategy extraction.",
    )
    maintenance_enabled: bool = Field(
        default=True, description="Run periodic L4 maintenance loops."
    )
    breaker_open_timeout_seconds: int = Field(
        default=600,
        description="Seconds an open breaker must be held before transitioning to half-open.",
    )
    breaker_halfopen_idle_seconds: int = Field(
        default=1800, description="Idle window in half-open before closing the breaker."
    )
    inactive_skill_retention_days: int = Field(
        default=30,
        description="Soft-delete skills with last_seen older than this and below the activity threshold.",
    )
    inactive_skill_min_attempts: int = Field(
        default=5, description="Minimum total_attempts to keep a skill regardless of last_seen."
    )


class CrossEncoderSettings(BaseModel):
    """Cross-encoder reranker model settings."""

    enabled: bool = Field(default=False)
    managed_model_id: Optional[str] = Field(default=None)
    variant: Optional[str] = Field(
        default=None,
        description=(
            "Optional ONNX quantization variant override (e.g. 'fp32', 'fp16', "
            "'quantized', 'arm64_int8', 'x86_avx512_int8'). When None, the "
            "platform default from the model's registry entry is used."
        ),
    )


class MemoryRerankerSettings(BaseModel):
    """Retrieval reranker settings.

    Heuristic reranking is always active. The cross-encoder is an optional
    second stage that adds semantic relevance scoring on top of heuristic
    metadata adjustments.
    """

    top_k: int = Field(default=8, ge=1)
    cross_encoder: CrossEncoderSettings = Field(default_factory=CrossEncoderSettings)


class QueryExpansionSettings(BaseModel):
    """LLM-based query expansion settings for retrieval."""

    enabled: bool = Field(default=True)
    max_expansions: int = Field(default=2, ge=1, le=5)


class GraphSpreadingSettings(BaseModel):
    """Graph spreading activation settings for L2 knowledge graph BFS."""

    enabled: bool = Field(default=True)


class EntitySemanticEdgeSettings(BaseModel):
    """Entity-scoped semantic edge builder settings."""

    enabled: bool = Field(default=False)


class MemorySettings(BaseModel):
    """Memory configuration."""

    db_path: str = Field(default="~/.magi/data/memory")
    retention_days: int = Field(default=90, ge=1)
    history_behavior: MemoryHistoryBehavior = Field(default=MemoryHistoryBehavior.DELETE)
    archive_path: str = Field(default="~/.magi/data/memory/archive")
    async_embeddings: bool = Field(default=True)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    reranker: MemoryRerankerSettings = Field(default_factory=MemoryRerankerSettings)
    query_expansion: QueryExpansionSettings = Field(default_factory=QueryExpansionSettings)
    graph_spreading: GraphSpreadingSettings = Field(default_factory=GraphSpreadingSettings)
    entity_semantic_edges: EntitySemanticEdgeSettings = Field(
        default_factory=EntitySemanticEdgeSettings
    )
    l0: MemoryL0Settings = Field(default_factory=MemoryL0Settings)
    l1: MemoryL1Settings = Field(default_factory=MemoryL1Settings)
    l2: MemoryL2Settings = Field(default_factory=MemoryL2Settings)
    l3: MemoryL3Settings = Field(default_factory=MemoryL3Settings)
    l4: MemoryL4Settings = Field(default_factory=MemoryL4Settings)

    @model_validator(mode="after")
    def enforce_fixed_vector_runtime(self) -> "MemorySettings":
        """Keep vector processing on the fixed async sqlite runtime path."""
        self.async_embeddings = True
        self.embedding.backend = EmbeddingBackend.SQLITE_VEC
        return self


__all__ = [
    "CrossEncoderSettings",
    "EmbeddingBackend",
    "EmbeddingMode",
    "EmbeddingSettings",
    "EntitySemanticEdgeSettings",
    "GraphSpreadingSettings",
    "LocalEmbeddingModelSource",
    "LocalEmbeddingSettings",
    "MemoryBackend",
    "MemoryHistoryBehavior",
    "MemoryL0Settings",
    "MemoryL1Settings",
    "MemoryL2AssertionSettings",
    "MemoryL2ConfidenceSettings",
    "MemoryL2EpisodeSettings",
    "MemoryL2ExperienceSettings",
    "MemoryL2LifecycleSettings",
    "MemoryL2LimitsSettings",
    "MemoryL2Settings",
    "MemoryL3Settings",
    "MemoryL4Settings",
    "MemoryRerankerSettings",
    "MemorySettings",
    "QueryExpansionSettings",
]
