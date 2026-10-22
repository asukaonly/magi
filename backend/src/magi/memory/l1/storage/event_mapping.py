"""Decode relational event records before crossing the repository boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...event_contracts import (
    IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth,
    author_type_label, content_type_label,
)
from ...evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
from ..embeddings.common import embedding_status_label
from ..ports import EventEvidence, MemoryEventRecord


def decode_event_metadata(raw_metadata: str | None) -> dict[str, Any] | None:
    metadata = json.loads(str(raw_metadata)) if raw_metadata else None
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("Persisted event metadata must be an object")
    return metadata


def event_record_from_mapping(row: Mapping[str, Any]) -> MemoryEventRecord:
    """Convert driver values, JSON and integer codes to domain types."""
    metadata = decode_event_metadata(row.get("metadata_json"))
    event = MemoryEvent(
        id=int(row["id"]),
        event_id=str(row["event_id"]),
        correlation_id=str(row["event_id"]),
        timestamp=float(row["timestamp"]),
        created_at=float(row["created_at"]),
        event_type=str(row["event_type"]),
        source=str(row["source"]),
        source_item_id=row["source_item_id"],
        idempotency_key=row["idempotency_key"],
        memory_domain=MemoryDomain.from_value(row["memory_domain"]),
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=bool(row["cognition_eligible"]),
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.from_value(row["retention_class"]),
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        session_seq=int(row["session_seq"]) if row.get("session_seq") is not None else None,
        user_id=row["user_id"],
        task_id=None,
        content=str(row["content"]),
        author_type=author_type_label(row["author_type"]),
        content_type=content_type_label(row["content_type"]),
        importance_score=float(row["importance_score"]),
        level=1,
        media_path=row["media_path"],
        metadata_json=metadata,
        embedding_status=embedding_status_label(row.get("embedding_status")),
        embedding_profile_id=row.get("embedding_profile_id"),
    )
    return MemoryEventRecord(
        event=event,
        evidence=EventEvidence(
            status=EvidenceStatus.from_value(row["evidence_status"]),
            classification=EvidenceClass.from_value(row["evidence_class"]),
            rule_version=int(row["evidence_rule_version"]),
            retrieval_scope=L1RetrievalScope.from_value(row["l1_retrieval_scope"]),
        ),
        embedding_chunk_count=int(row.get("embedding_chunk_count") or 0),
        last_embedded_at=float(row["last_embedded_at"]) if row.get("last_embedded_at") is not None else None,
        deleted_at=float(row["deleted_at"]) if row.get("deleted_at") is not None else None,
    )
