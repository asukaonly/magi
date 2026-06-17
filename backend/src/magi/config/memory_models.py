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
    runtime_replay_include_l0_only: bool = Field(default=False)


class MemoryL1Settings(BaseModel):
    """L1 long-term event memory settings."""

    enabled: bool = Field(default=True)
    retention_days: int = Field(default=7, ge=1)
    t1_importance_enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)


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
    derive_schedule_enabled: bool = Field(
        default=True,
        description="Register periodic L2 derived-data (interest aggregation + conflict notifications) task, independent of maintenance.",
    )
    derive_schedule_interval_seconds: float = Field(
        default=21_600.0,
        ge=300.0,
        description="Interval between L2 derive runs (seconds). Minimum 300s.",
    )


class MemoryL3Settings(BaseModel):
    """L3 reflection-memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    llm_summary_enabled: bool = Field(default=True)
    temporal_llm_timeout_seconds: float = Field(default=3.0, ge=0.1)
    temporal_llm_min_event_count: int = Field(default=2, ge=1)
    summary_interval_minutes: int = Field(default=60, ge=1)
    digest_enabled: bool = Field(default=True)
    digest_interval_hours: int = Field(default=24, ge=1)


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


class GraphSpreadingSettings(BaseModel):
    """Graph spreading activation settings for L2 knowledge graph BFS."""

    enabled: bool = Field(default=False)


class EntitySemanticEdgeSettings(BaseModel):
    """Entity-scoped semantic edge builder settings."""

    enabled: bool = Field(default=False)


class MemorySettings(BaseModel):
    """Memory configuration."""

    db_path: str = Field(default="~/.magi/data/memory")
    retention_days: int = Field(default=90, ge=1)
    history_behavior: MemoryHistoryBehavior = Field(default=MemoryHistoryBehavior.DELETE)
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
    "MemoryL2Settings",
    "MemoryL3Settings",
    "MemoryL4Settings",
    "MemoryRerankerSettings",
    "MemorySettings",
    "QueryExpansionSettings",
]
