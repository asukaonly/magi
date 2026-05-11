"""Row serialization helpers for the canonical L1 event store."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from ...event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth

EMBEDDING_STATUS_DISABLED = "disabled"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_SKIPPED = "skipped"
EMBEDDING_STATUS_STALE = "stale"


class _L1EventRowHostProtocol(Protocol):
    _embedding_service: Any

    def _vectors_enabled(self) -> bool: ...


class L1EventRowMixin:
    """Convert SQLite rows into API dictionaries and memory contracts."""

    def _effective_embedding_status(
        self,
        stored_status: str,
        stored_profile_id: str | None,
        *,
        active_profile_id: str | None = None,
        memory_domain: MemoryDomain | None = None,
    ) -> str:
        host = cast(_L1EventRowHostProtocol, self)
        normalized_status = str(stored_status or EMBEDDING_STATUS_DISABLED)
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

    def _row_to_dict(
        self,
        row: aiosqlite.Row,
        *,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        active_embedding_profile_id: str | None = None,
    ) -> Dict[str, Any]:
        stored_profile_id = row["embedding_profile_id"]
        metadata_json = row["metadata_json"] if include_metadata_json else None
        memory_domain = MemoryDomain.from_value(row["memory_domain"])
        item = {
            "id": int(row["id"]),
            "event_id": str(row["event_id"]),
            "correlation_id": str(row["correlation_id"]),
            "timestamp": float(row["timestamp"]),
            "created_at": float(row["created_at"]),
            "event_type": str(row["event_type"]),
            "source": str(row["source"]),
            "source_item_id": row["source_item_id"],
            "idempotency_key": row["idempotency_key"],
            "memory_domain": memory_domain.label,
            "ingest_target": IngestTarget.from_value(row["ingest_target"]).label,
            "cognition_eligible": bool(row["cognition_eligible"]),
            "tom_depth": TomDepth.from_value(row["tom_depth"]).label,
            "retention_class": RetentionClass.from_value(row["retention_class"]).label,
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "user_id": row["user_id"],
            "task_id": row["task_id"],
            "content": str(row["content"]),
            "author_type": str(row["author_type"]),
            "content_type": str(row["content_type"]),
            "importance_score": float(row["importance_score"]),
            "level": int(row["level"]),
            "media_path": row["media_path"],
            "metadata_json": json.loads(str(metadata_json)) if metadata_json else None,
            "evidence_status": str(row["evidence_status"]),
            "evidence_class": str(row["evidence_class"]),
            "evidence_reason_code": str(row["evidence_reason_code"]),
            "evidence_speaker_role": row["evidence_speaker_role"],
            "evidence_grounding_type": row["evidence_grounding_type"],
            "evidence_semantic_owner": row["evidence_semantic_owner"],
            "evidence_originality_type": row["evidence_originality_type"],
            "evidence_source_event_ids": json.loads(
                str(row["evidence_source_event_ids_json"] or "[]")
            ),
            "evidence_confidence": float(row["evidence_confidence"] or 0.0),
            "evidence_classifier_version": str(row["evidence_classifier_version"]),
            "evidence_policy_version": str(row["evidence_policy_version"]),
            "l1_retrieval_scope": str(row["l1_retrieval_scope"]),
            "l2_graph_scope": str(row["l2_graph_scope"]),
            "l2_assertion_scope": str(row["l2_assertion_scope"]),
            "evidence_skip_reason": row["evidence_skip_reason"],
            "evidence_updated_at": float(row["evidence_updated_at"])
            if row["evidence_updated_at"] is not None
            else None,
            "embedding_chunk_count": int(row["embedding_chunk_count"] or 0),
            "last_embedded_at": float(row["last_embedded_at"])
            if row["last_embedded_at"] is not None
            else None,
            "deleted_at": float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        }
        if include_embedding_fields:
            item["embedding_status"] = self._effective_embedding_status(
                row["embedding_status"],
                stored_profile_id,
                active_profile_id=active_embedding_profile_id,
                memory_domain=memory_domain,
            )
            item["embedding_profile_id"] = stored_profile_id
        return item

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent:
        stored_profile_id = row["embedding_profile_id"]
        metadata_json = row["metadata_json"]
        memory_domain = MemoryDomain.from_value(row["memory_domain"])
        return MemoryEvent(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            correlation_id=str(row["correlation_id"]),
            timestamp=float(row["timestamp"]),
            created_at=float(row["created_at"]),
            event_type=str(row["event_type"]),
            source=str(row["source"]),
            source_item_id=row["source_item_id"],
            idempotency_key=row["idempotency_key"],
            memory_domain=memory_domain,
            ingest_target=IngestTarget.from_value(row["ingest_target"]),
            cognition_eligible=bool(row["cognition_eligible"]),
            tom_depth=TomDepth.from_value(row["tom_depth"]),
            retention_class=RetentionClass.from_value(row["retention_class"]),
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            content=str(row["content"]),
            author_type=str(row["author_type"]),
            content_type=str(row["content_type"]),
            importance_score=float(row["importance_score"]),
            level=int(row["level"]),
            media_path=row["media_path"],
            metadata_json=json.loads(str(metadata_json)) if metadata_json else None,
            embedding_status=self._effective_embedding_status(
                row["embedding_status"],
                stored_profile_id,
                memory_domain=memory_domain,
            ),
            embedding_profile_id=stored_profile_id,
        )

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
        raw_timeline = metadata.get("timeline")
        timeline: Dict[str, Any] = (
            cast(Dict[str, Any], raw_timeline) if isinstance(raw_timeline, dict) else {}
        )
        if not timeline:
            return None
        return {
            "event_id": str(event["event_id"]),
            "source_type": str(timeline.get("source_type") or event.get("source") or "memory"),
            "source_item_id": (
                timeline.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
            ),
            "occurred_at": float(event.get("timestamp") or event.get("created_at") or 0.0),
            "title": str(
                timeline.get("title") or event.get("content") or event.get("event_id") or "Event"
            ),
            "summary": str(timeline.get("summary") or event.get("content") or ""),
        }
