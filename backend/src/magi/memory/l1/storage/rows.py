"""Row serialization helpers for the canonical L1 event store."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from magi.events.source_activity_snapshot import activity_snapshot_from_metadata

from ...event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
    author_type_label,
    content_type_label,
)
from ...evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
from ..embeddings.common import embedding_status_label

EMBEDDING_STATUS_DISABLED = "disabled"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_SKIPPED = "skipped"
EMBEDDING_STATUS_STALE = "stale"


class _L1EventRowHostProtocol(Protocol):
    _embedding_service: Any

    def _vectors_enabled(self) -> bool: ...


class L1EventRowMixin:
    """Convert SQLite rows into API dictionaries and memory contracts."""

    @staticmethod
    def _row_value(row: aiosqlite.Row, key: str, default: Any = None) -> Any:
        return row[key] if key in row.keys() else default

    def _effective_embedding_status(
        self,
        stored_status: str,
        stored_profile_id: str | None,
        *,
        active_profile_id: str | None = None,
        memory_domain: MemoryDomain | None = None,
    ) -> str:
        host = cast(_L1EventRowHostProtocol, self)
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

    def _row_to_dict(
        self,
        row: aiosqlite.Row,
        *,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        active_embedding_profile_id: str | None = None,
    ) -> Dict[str, Any]:
        stored_profile_id = self._row_value(row, "embedding_profile_id")
        metadata_json = row["metadata_json"] if include_metadata_json else None
        memory_domain = MemoryDomain.from_value(row["memory_domain"])
        session_seq = self._row_value(row, "session_seq")
        item = {
            "id": int(row["id"]),
            "event_id": str(row["event_id"]),
            "timestamp": float(row["timestamp"]),
            "created_at": float(row["created_at"]),
            "event_type": str(row["event_type"]),
            "source": str(row["source"]),
            "source_item_id": row["source_item_id"],
            "idempotency_key": row["idempotency_key"],
            "memory_domain": memory_domain.label,
            "ingest_target": IngestTarget.L1_ONLY.label,
            "cognition_eligible": bool(row["cognition_eligible"]),
            "tom_depth": TomDepth.NONE.label,
            "retention_class": RetentionClass.from_value(row["retention_class"]).label,
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "session_seq": int(session_seq) if session_seq is not None else None,
            "user_id": row["user_id"],
            "content": str(row["content"]),
            "author_type": author_type_label(row["author_type"]),
            "content_type": content_type_label(row["content_type"]),
            "importance_score": float(row["importance_score"]),
            "media_path": row["media_path"],
            "metadata_json": json.loads(str(metadata_json)) if metadata_json else None,
            "evidence_status": EvidenceStatus.from_value(row["evidence_status"]).label,
            "evidence_class": EvidenceClass.from_value(row["evidence_class"]).label,
            "evidence_rule_version": int(row["evidence_rule_version"]),
            "l1_retrieval_scope": L1RetrievalScope.from_value(row["l1_retrieval_scope"]).label,
            "embedding_chunk_count": int(self._row_value(row, "embedding_chunk_count") or 0),
            "last_embedded_at": float(self._row_value(row, "last_embedded_at"))
            if self._row_value(row, "last_embedded_at") is not None
            else None,
            "deleted_at": float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        }
        if include_embedding_fields:
            item["embedding_status"] = self._effective_embedding_status(
                self._row_value(row, "embedding_status"),
                stored_profile_id,
                active_profile_id=active_embedding_profile_id,
                memory_domain=memory_domain,
            )
            item["embedding_profile_id"] = stored_profile_id
        return item

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent:
        stored_profile_id = self._row_value(row, "embedding_profile_id")
        metadata_json = row["metadata_json"]
        memory_domain = MemoryDomain.from_value(row["memory_domain"])
        session_seq = self._row_value(row, "session_seq")
        return MemoryEvent(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            correlation_id=str(row["event_id"]),
            timestamp=float(row["timestamp"]),
            created_at=float(row["created_at"]),
            event_type=str(row["event_type"]),
            source=str(row["source"]),
            source_item_id=row["source_item_id"],
            idempotency_key=row["idempotency_key"],
            memory_domain=memory_domain,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=bool(row["cognition_eligible"]),
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.from_value(row["retention_class"]),
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            session_seq=int(session_seq) if session_seq is not None else None,
            user_id=row["user_id"],
            task_id=None,
            content=str(row["content"]),
            author_type=author_type_label(row["author_type"]),
            content_type=content_type_label(row["content_type"]),
            importance_score=float(row["importance_score"]),
            level=1,
            media_path=row["media_path"],
            metadata_json=json.loads(str(metadata_json)) if metadata_json else None,
            embedding_status=self._effective_embedding_status(
                self._row_value(row, "embedding_status"),
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
