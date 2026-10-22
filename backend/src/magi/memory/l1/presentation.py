"""Presentation of typed memory records without driver-specific conversion."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional, Protocol, cast

from magi.events.source_activity_snapshot import activity_snapshot_from_metadata

from ..event_contracts import MemoryDomain, MemoryEvent
from .ports import MemoryEventRecord
from .embeddings.common import embedding_status_label

EMBEDDING_STATUS_DISABLED = "disabled"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_SKIPPED = "skipped"
EMBEDDING_STATUS_STALE = "stale"


class _L1EventPresentationHostProtocol(Protocol):
    _embedding_service: Any

    def _vectors_enabled(self) -> bool: ...


class L1EventPresentationMixin:
    """Render repository records as product payloads and memory contracts."""


    def _effective_embedding_status(
        self,
        stored_status: str,
        stored_profile_id: str | None,
        *,
        active_profile_id: str | None = None,
        memory_domain: MemoryDomain | None = None,
    ) -> str:
        host = cast(_L1EventPresentationHostProtocol, self)
        normalized_status = embedding_status_label(stored_status)
        if not host._vectors_enabled() or host._embedding_service is None:
            if memory_domain is not None and memory_domain in {
                MemoryDomain.RUNTIME_TELEMETRY,
                MemoryDomain.SYSTEM_CONTROL,
            }:
                return EMBEDDING_STATUS_SKIPPED
            return EMBEDDING_STATUS_DISABLED
        if normalized_status != EMBEDDING_STATUS_READY:
            return normalized_status
        if active_profile_id and stored_profile_id and stored_profile_id != active_profile_id:
            return EMBEDDING_STATUS_STALE
        return normalized_status


    def _record_to_dict(
        self, record: MemoryEventRecord, *, include_embedding_fields: bool = True,
        active_embedding_profile_id: str | None = None,
    ) -> Dict[str, Any]:
        event = record.event
        item = {
            "id": event.id, "event_id": event.event_id,
            "timestamp": event.timestamp, "created_at": event.created_at,
            "event_type": event.event_type, "source": event.source,
            "source_item_id": event.source_item_id, "idempotency_key": event.idempotency_key,
            "memory_domain": event.memory_domain.label, "ingest_target": event.ingest_target.label,
            "cognition_eligible": event.cognition_eligible, "tom_depth": event.tom_depth.label,
            "retention_class": event.retention_class.label, "session_id": event.session_id,
            "turn_id": event.turn_id, "session_seq": event.session_seq, "user_id": event.user_id,
            "content": event.content, "author_type": event.author_type, "content_type": event.content_type,
            "importance_score": event.importance_score, "media_path": event.media_path,
            "metadata_json": event.metadata_json,
            "evidence_status": record.evidence.status.label,
            "evidence_class": record.evidence.classification.label,
            "evidence_rule_version": record.evidence.rule_version,
            "l1_retrieval_scope": record.evidence.retrieval_scope.label,
            "embedding_chunk_count": record.embedding_chunk_count,
            "last_embedded_at": record.last_embedded_at, "deleted_at": record.deleted_at,
        }
        if include_embedding_fields:
            item["embedding_status"] = self._effective_embedding_status(
                event.embedding_status, event.embedding_profile_id,
                active_profile_id=active_embedding_profile_id, memory_domain=event.memory_domain,
            )
            item["embedding_profile_id"] = event.embedding_profile_id
        return item

    def _record_to_memory_event(self, record: MemoryEventRecord) -> MemoryEvent:
        event = record.event
        return replace(event, embedding_status=self._effective_embedding_status(
            event.embedding_status, event.embedding_profile_id, memory_domain=event.memory_domain,
        ))


    @staticmethod
    def _to_timeline_view(event: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if event is None:
            return None
        raw_metadata = event.get("metadata")
        metadata: Dict[str, Any] = (
            cast(Dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
        )
        if not metadata:
            raw_metadata_json = event.get("metadata_json")
            metadata = (
                cast(Dict[str, Any], raw_metadata_json)
                if isinstance(raw_metadata_json, dict)
                else {}
            )
        activity_snapshot = activity_snapshot_from_metadata(metadata)
        if not activity_snapshot:
            return None
        return {
            "event_id": str(event["event_id"]),
            "source_type": str(activity_snapshot.get("source_type") or event.get("source") or "memory"),
            "source_item_id": (
                activity_snapshot.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
            ),
            "occurred_at": float(event.get("timestamp") or event.get("created_at") or 0.0),
            "title": str(
                activity_snapshot.get("title")
                or event.get("content")
                or event.get("event_id")
                or "Event"
            ),
            "summary": str(activity_snapshot.get("summary") or event.get("content") or ""),
        }
