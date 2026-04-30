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


class MemoryL1Settings(BaseModel):
    """L1 long-term event memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)


class MemoryL2Settings(BaseModel):
    """L2 structured cognition settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    batch_flush_interval_seconds: int = Field(default=60, ge=30)
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
    maintenance_min_mentions: int = Field(
        default=2,
        ge=1,
        description="Orphan prune keeps entities with at least this many resolved mentions (unless referenced in graph).",
    )


class MemoryL3Settings(BaseModel):
    """L3 reflection-memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    llm_summary_enabled: bool = Field(default=True)
    temporal_llm_timeout_seconds: float = Field(default=3.0, ge=0.1)
    temporal_llm_min_event_count: int = Field(default=2, ge=1)
    summary_interval_minutes: int = Field(default=60, ge=1)


class MemoryL4Settings(BaseModel):
    """L4 procedural-memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    strategy_extraction_threshold: int = Field(
        default=5,
        description="Number of new traces before triggering LLM strategy extraction.",
    )


class CrossEncoderSettings(BaseModel):
    """Cross-encoder reranker model settings."""

    enabled: bool = Field(default=False)
    managed_model_id: Optional[str] = Field(default=None)


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
    entity_semantic_edges: EntitySemanticEdgeSettings = Field(default_factory=EntitySemanticEdgeSettings)
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