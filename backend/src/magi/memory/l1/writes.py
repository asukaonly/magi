"""Write and destructive maintenance operations for L1 event storage."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional, Protocol, cast

from ...core.sqlite import sqlite_connection_async
from ...events.events import EventTypes
from ..embedding.sqlite_vec_index import SqliteVecIndex
from ..evidence import (
    EVIDENCE_CLASSIFIER_VERSION,
    EVIDENCE_POLICY_VERSION,
    classify_event_evidence,
    resolve_l2_policy,
)
from ..event_contracts import MemoryEvent
from ..hybrid_retrieval.fts_utils import tokenize_for_fts
from .chat_sessions import project_chat_event_to_session
from .embeddings.common import EVENT_CHUNKS_TABLE, FACT_EVENTS_TABLE

logger = logging.getLogger(__name__)

L1_STORE_DIAGNOSTIC_EVENT_TYPES = {
    EventTypes.USER_MESSAGE,
    EventTypes.AI_RESPONSE,
    EventTypes.ACTION_EXECUTED,
}


class L1EventWriteHostProtocol(Protocol):
    db_path: str
    _embedding_queue: Any | None
    _embedding_workers: list[asyncio.Task[None]]
    _initialized: bool
    _vector_index: SqliteVecIndex | None

    async def initialize(self) -> None: ...

    def get_search_text(self, event: MemoryEvent) -> str: ...

    def _initial_embedding_status(self, event: MemoryEvent) -> str: ...

    def _initial_embedding_profile_id(self, event: MemoryEvent) -> str | None: ...

    async def _resolve_existing_event_id(self, db: Any, event: MemoryEvent) -> str | None: ...

    async def _schedule_event_embedding(self, event: MemoryEvent) -> None: ...

    async def count_events(self) -> int: ...

    async def _list_chunk_ids_for_event(self, event_id: str) -> list[str]: ...


class L1EventWriteMixin:
    """Persist, clear, and soft-delete normalized L1 memory events."""

    async def store(self, event: MemoryEvent) -> str:
        """Persist a normalized memory event."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        if event.source == "calendar":
            logger.info(
                "L1EventStore storing calendar event | "
                "event_id=%s event_type=%s source_item_id=%s content=%s metadata_json=%s",
                event.event_id,
                event.event_type,
                event.source_item_id,
                event.content,
                event.metadata_json,
            )
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore persisting event | event_id=%s type=%s session_id=%s user_id=%s correlation_id=%s",
                event.event_id,
                event.event_type,
                event.session_id,
                event.user_id,
                event.correlation_id,
            )
        evidence_values = self._resolve_event_evidence_values(event)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                f"""
                INSERT OR IGNORE INTO {FACT_EVENTS_TABLE}(
                    event_id, correlation_id, timestamp, created_at,
                    event_type, source, source_item_id, idempotency_key, memory_domain, ingest_target,
                    cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                    task_id, content, author_type, content_type, importance_score,
                    level, media_path, metadata_json, embedding_status, embedding_profile_id,
                    embedding_chunk_count, last_embedded_at, deleted_at,
                    causation_id, trace_id, span_id, parent_span_id,
                    evidence_status, evidence_class, evidence_reason_code,
                    evidence_speaker_role, evidence_grounding_type, evidence_semantic_owner,
                    evidence_originality_type, evidence_source_event_ids_json,
                    evidence_confidence, evidence_classifier_version, evidence_policy_version,
                    l1_retrieval_scope, l2_graph_scope, l2_assertion_scope,
                    evidence_skip_reason, evidence_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.correlation_id,
                    float(event.timestamp),
                    float(event.created_at),
                    event.event_type,
                    event.source,
                    event.source_item_id,
                    event.idempotency_key,
                    int(event.memory_domain),
                    int(event.ingest_target),
                    1 if event.cognition_eligible else 0,
                    int(event.tom_depth),
                    int(event.retention_class),
                    event.session_id,
                    event.turn_id,
                    event.user_id,
                    event.task_id,
                    event.content,
                    event.author_type,
                    event.content_type,
                    float(event.importance_score),
                    int(event.level),
                    event.media_path,
                    json.dumps(event.metadata_json) if event.metadata_json is not None else None,
                    host._initial_embedding_status(event),
                    host._initial_embedding_profile_id(event),
                    0,
                    None,
                    None,
                    event.causation_id,
                    event.trace_id,
                    event.span_id,
                    event.parent_span_id,
                    evidence_values["evidence_status"],
                    evidence_values["evidence_class"],
                    evidence_values["evidence_reason_code"],
                    evidence_values["evidence_speaker_role"],
                    evidence_values["evidence_grounding_type"],
                    evidence_values["evidence_semantic_owner"],
                    evidence_values["evidence_originality_type"],
                    evidence_values["evidence_source_event_ids_json"],
                    evidence_values["evidence_confidence"],
                    evidence_values["evidence_classifier_version"],
                    evidence_values["evidence_policy_version"],
                    evidence_values["l1_retrieval_scope"],
                    evidence_values["l2_graph_scope"],
                    evidence_values["l2_assertion_scope"],
                    evidence_values["evidence_skip_reason"],
                    evidence_values["evidence_updated_at"],
                ),
            )
            inserted = cursor.rowcount > 0
            if not inserted:
                await db.rollback()
                existing_event_id = await host._resolve_existing_event_id(db, event)
                if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
                    logger.info(
                        "L1EventStore skipped duplicate event | event_id=%s type=%s",
                        event.event_id,
                        event.event_type,
                    )
                return existing_event_id or event.event_id
            tokenized = tokenize_for_fts(host.get_search_text(event))
            await db.execute(
                "DELETE FROM l1_events_fts WHERE event_id = ?",
                (event.event_id,),
            )
            await db.execute(
                "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                (event.event_id, tokenized),
            )
            await project_chat_event_to_session(
                db,
                user_id=event.user_id,
                session_id=event.session_id,
                event_type=event.event_type,
                content=event.content,
                timestamp=float(event.timestamp),
            )
            await db.commit()
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore persisted event | event_id=%s type=%s",
                event.event_id,
                event.event_type,
            )
        await host._schedule_event_embedding(event)
        return event.event_id

    def _resolve_event_evidence_values(self, event: MemoryEvent) -> dict[str, Any]:
        now = time.time()
        try:
            classification = classify_event_evidence(event)
        except Exception as exc:
            logger.warning(
                "L1 evidence classification failed | event_id=%s error=%s",
                event.event_id,
                exc,
            )
            return {
                "evidence_status": "classification_error",
                "evidence_class": "unknown",
                "evidence_reason_code": "classifier_error",
                "evidence_speaker_role": event.author_type,
                "evidence_grounding_type": None,
                "evidence_semantic_owner": None,
                "evidence_originality_type": None,
                "evidence_source_event_ids_json": "[]",
                "evidence_confidence": 0.0,
                "evidence_classifier_version": EVIDENCE_CLASSIFIER_VERSION,
                "evidence_policy_version": "unresolved",
                "l1_retrieval_scope": "none",
                "l2_graph_scope": "none",
                "l2_assertion_scope": "none",
                "evidence_skip_reason": "classification_error",
                "evidence_updated_at": now,
            }

        try:
            policy = resolve_l2_policy(classification)
        except Exception as exc:
            logger.warning(
                "L1 evidence policy resolution failed | event_id=%s evidence_class=%s error=%s",
                event.event_id,
                classification.evidence_class,
                exc,
            )
            return {
                "evidence_status": "policy_error",
                "evidence_class": classification.evidence_class,
                "evidence_reason_code": classification.reason_code,
                "evidence_speaker_role": classification.speaker_role,
                "evidence_grounding_type": classification.grounding_type,
                "evidence_semantic_owner": classification.semantic_owner,
                "evidence_originality_type": classification.originality_type,
                "evidence_source_event_ids_json": json.dumps(classification.source_event_ids),
                "evidence_confidence": float(classification.confidence),
                "evidence_classifier_version": EVIDENCE_CLASSIFIER_VERSION,
                "evidence_policy_version": EVIDENCE_POLICY_VERSION,
                "l1_retrieval_scope": "none",
                "l2_graph_scope": "none",
                "l2_assertion_scope": "none",
                "evidence_skip_reason": "policy_error",
                "evidence_updated_at": now,
            }

        return {
            "evidence_status": "classified",
            "evidence_class": classification.evidence_class,
            "evidence_reason_code": classification.reason_code,
            "evidence_speaker_role": classification.speaker_role,
            "evidence_grounding_type": classification.grounding_type,
            "evidence_semantic_owner": classification.semantic_owner,
            "evidence_originality_type": classification.originality_type,
            "evidence_source_event_ids_json": json.dumps(classification.source_event_ids),
            "evidence_confidence": float(classification.confidence),
            "evidence_classifier_version": EVIDENCE_CLASSIFIER_VERSION,
            "evidence_policy_version": EVIDENCE_POLICY_VERSION,
            "l1_retrieval_scope": policy.l1_retrieval_scope,
            "l2_graph_scope": policy.graph_scope,
            "l2_assertion_scope": policy.assertion_scope,
            "evidence_skip_reason": policy.skip_reason,
            "evidence_updated_at": now,
        }

    async def clear(self) -> int:
        """Delete all events by dropping and recreating the DB file."""
        host = cast(L1EventWriteHostProtocol, self)
        logger.info("L1EventStore.clear: counting events before wipe")
        count = await host.count_events()
        logger.info("L1EventStore.clear: total=%d, stopping embedding workers", count)

        if host._embedding_queue is not None and host._embedding_workers:
            for _ in host._embedding_workers:
                await host._embedding_queue.put(None)
            await asyncio.gather(*host._embedding_workers, return_exceptions=True)
            host._embedding_workers = []
            logger.info("L1EventStore.clear: embedding workers stopped")

        if host._vector_index is not None:
            logger.info("L1EventStore.clear: closing vec index connection")
            await host._vector_index.close()

        db_path = Path(host.db_path)
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(db_path) + suffix)
            if path.exists():
                logger.info("L1EventStore.clear: deleting %s", path)
                path.unlink()

        host._initialized = False
        logger.info("L1EventStore.clear: reinitializing schema at %s", db_path)

        await host.initialize()
        logger.info("L1EventStore.clear: done, removed %d events", count)

        return count

    async def mark_deleted(self, event_id: str, *, deleted_at: Optional[float] = None) -> bool:
        """Soft-delete an event."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        deleted_timestamp = float(deleted_at or time.time())
        chunk_ids = await host._list_chunk_ids_for_event(event_id)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                f"UPDATE {FACT_EVENTS_TABLE} SET deleted_at = ? WHERE event_id = ?",
                (deleted_timestamp, event_id),
            )
            if cursor.rowcount > 0:
                await db.execute(
                    "DELETE FROM l1_events_fts WHERE event_id = ?",
                    (event_id,),
                )
                await db.execute(
                    f"DELETE FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                    (event_id,),
                )
            await db.commit()
        if cursor.rowcount > 0 and host._vector_index is not None:
            for chunk_id in chunk_ids:
                await host._vector_index.delete_entity(entity_id=chunk_id)
        return cursor.rowcount > 0


__all__ = ["L1EventWriteMixin", "L1_STORE_DIAGNOSTIC_EVENT_TYPES"]
