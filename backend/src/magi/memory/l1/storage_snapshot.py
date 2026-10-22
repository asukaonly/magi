"""Validated logical event state, independent of SQL dialects and vector backends."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..event_contracts import AuthorType, ContentType, MemoryDomain, RetentionClass
from .embeddings.common import EmbeddingStatus
from ..evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope


class SnapshotRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FactSnapshot(SnapshotRecord):
    id: int = Field(gt=0)
    event_id: str
    timestamp: float
    created_at: float
    event_type: str
    source: str
    source_item_id: str | None
    idempotency_key: str | None
    memory_domain: MemoryDomain
    cognition_eligible: Literal[0, 1]
    retention_class: RetentionClass
    session_id: str | None
    turn_id: str | None
    session_seq: int | None = Field(ge=0)
    user_id: str | None
    content: str
    author_type: AuthorType
    content_type: ContentType
    importance_score: float
    media_path: str | None
    metadata: dict | None
    deleted_at: float | None
    evidence_status: EvidenceStatus
    evidence_class: EvidenceClass
    evidence_rule_version: int
    l1_retrieval_scope: L1RetrievalScope


class SessionSequenceSnapshot(SnapshotRecord):
    session_id: str
    next_seq: int = Field(ge=0)
    updated_at: float


class EventEmbeddingSnapshot(SnapshotRecord):
    event_id: str
    embedding_status: EmbeddingStatus
    embedding_profile_id: str | None
    embedding_chunk_count: int = Field(ge=0)
    last_embedded_at: float | None
    updated_at: float


class PayloadSnapshot(SnapshotRecord):
    event_id: str
    content: str
    created_at: float


class CognitionHandoffSnapshot(SnapshotRecord):
    event_id: str
    created_at: float
    available_at: float
    attempt_count: int = Field(ge=0)
    last_error: str | None


class FacetSnapshot(SnapshotRecord):
    event_id: str
    source: str
    facet_name: str
    text_value: str | None
    normalized_text_value: str | None
    numeric_value: float | None
    timestamp_value: float | None
    json_value: str | None
    created_at: float


class EmbeddingProfileSnapshot(SnapshotRecord):
    profile_id: str
    provider_name: str
    model_name: str
    embedding_dim: int | None = Field(gt=0)
    text_builder_version: str
    created_at: float


class ChunkSnapshot(SnapshotRecord):
    chunk_id: str
    event_id: str
    chunk_index: int = Field(ge=0)
    chunk_text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    token_estimate: int = Field(ge=0)
    embedding_profile_id: str | None
    created_at: float
    updated_at: float


class EntityLinkSnapshot(SnapshotRecord):
    event_id: str
    entity_id: str
    entity_type: str | None
    confidence: float | None
    created_at: float


class ProjectedEntitySnapshot(EntityLinkSnapshot):
    revision: int = Field(gt=0)
    lease_token: str
    attempt_count: int = Field(gt=0)


class EntityProjectionSnapshot(SnapshotRecord):
    event_id: str
    revision: int = Field(gt=0)
    lease_token: str
    attempt_count: int = Field(gt=0)
    payload_fingerprint: str
    applied_at: float


class SessionPreviewSnapshot(SnapshotRecord):
    session_id: str
    user_id: str
    title: str
    title_overridden: Literal[0, 1]
    summary: str
    created_at: float
    updated_at: float
    last_message_at: float | None
    last_user_message_at: float | None
    last_message_preview: str
    last_user_message_preview: str
    message_count: int = Field(ge=0)
    workspace_path: str | None
    archived_at: float | None
    deleted_at: float | None


class EventStorageSnapshot(SnapshotRecord):
    """Complete event-owner state; lexical and remote vector indexes are rebuildable."""

    version: Literal[1] = 1
    event_sequence: int = Field(ge=0)
    entity_link_generation: int = Field(ge=0)
    facts: list[FactSnapshot] = Field(default_factory=list)
    sequences: list[SessionSequenceSnapshot] = Field(default_factory=list)
    embeddings: list[EventEmbeddingSnapshot] = Field(default_factory=list)
    payloads: list[PayloadSnapshot] = Field(default_factory=list)
    handoffs: list[CognitionHandoffSnapshot] = Field(default_factory=list)
    facets: list[FacetSnapshot] = Field(default_factory=list)
    profiles: list[EmbeddingProfileSnapshot] = Field(default_factory=list)
    chunks: list[ChunkSnapshot] = Field(default_factory=list)
    entities: list[EntityLinkSnapshot] = Field(default_factory=list)
    projection_state: list[EntityProjectionSnapshot] = Field(default_factory=list)
    projected_entities: list[ProjectedEntitySnapshot] = Field(default_factory=list)
    sessions: list[SessionPreviewSnapshot] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_relations(self) -> EventStorageSnapshot:
        for records, names in (
            (self.facts, ("event_id",)),
            (self.facts, ("id",)),
            (self.sequences, ("session_id",)),
            (self.embeddings, ("event_id",)),
            (self.payloads, ("event_id",)),
            (self.handoffs, ("event_id",)),
            (self.profiles, ("profile_id",)),
            (self.chunks, ("chunk_id",)),
            (self.entities, ("event_id", "entity_id")),
            (self.projection_state, ("event_id",)),
            (self.projected_entities, ("event_id", "entity_id")),
            (self.sessions, ("session_id",)),
        ):
            keys = [tuple(getattr(row, name) for name in names) for row in records]
            if len(set(keys)) != len(keys):
                raise ValueError("Event snapshot contains duplicate identities")
        facts = {row.event_id: row for row in self.facts}
        if max((row.id for row in self.facts), default=0) > self.event_sequence:
            raise ValueError("Event snapshot sequence precedes its facts")
        dedup = [
            (row.source, row.event_type, row.idempotency_key)
            for row in self.facts
            if row.idempotency_key is not None
        ]
        if len(set(dedup)) != len(dedup):
            raise ValueError("Event snapshot contains duplicate source identities")
        for rows in (self.embeddings, self.payloads, self.handoffs, self.facets, self.chunks):
            if any(row.event_id not in facts for row in rows):
                raise ValueError("Event snapshot contains orphaned side records")
        for row in self.handoffs:
            if (
                facts[row.event_id].deleted_at is not None
                or not facts[row.event_id].cognition_eligible
            ):
                raise ValueError("Event snapshot has a handoff for an ineligible source")
        projected = {row.event_id: row for row in self.projection_state}
        for row in self.projected_entities:
            state = projected.get(row.event_id)
            if state is None or (state.revision, state.lease_token, state.attempt_count) != (
                row.revision,
                row.lease_token,
                row.attempt_count,
            ):
                raise ValueError("Event snapshot projection state does not match its links")
        next_sequences = {row.session_id: row.next_seq for row in self.sequences}
        for row in self.facts:
            if (
                row.session_id
                and row.session_seq is not None
                and next_sequences.get(row.session_id.strip(), -1) <= row.session_seq
            ):
                raise ValueError("Event snapshot session sequence precedes its facts")
        return self

    def is_empty(self) -> bool:
        return (
            self.event_sequence == 0
            and self.entity_link_generation == 0
            and not any(
                getattr(self, name)
                for name in type(self).model_fields
                if name not in {"version", "event_sequence", "entity_link_generation"}
            )
        )


class EventStateTransfer(Protocol):
    async def export_state(self) -> EventStorageSnapshot: ...

    async def import_state(
        self, snapshot: EventStorageSnapshot, *, replace: bool = False
    ) -> None: ...
