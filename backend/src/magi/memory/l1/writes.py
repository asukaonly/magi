"""Write and destructive maintenance operations for L1 event storage."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, cast

from ...events.events import EventTypes
from ...utils.diagnostic_logging import full_content_logging_enabled
from ...utils.calendar_timezone import (
    calendar_timezone_id_from_metadata,
    local_calendar_timezone_id,
    with_calendar_timezone,
)
from ..embedding.ports import VectorIndex
from ..evidence import (
    EVIDENCE_RULE_VERSION,
    EvidenceClass,
    EvidenceStatus,
    L1RetrievalScope,
    classify_event_evidence,
    resolve_l2_policy,
)
from ..event_contracts import MemoryEvent
from .ports import EventAppend, EventEvidence, MemoryEventRepository
from .maintenance_contracts import EvidenceAnnotationUpdate, EvidenceBackfillQuery
from .source_facets import extract_source_facets

logger = logging.getLogger(__name__)


def _merge_evidence_into_metadata(
    metadata_json: dict | None, reason_code: str | None
) -> dict | None:
    """Embed the governance reason_code under a ``_evidence`` namespace inside
    the event's metadata_json, preserving the event's own keys.

    Returns None only when there is nothing to store (no reason_code and no
    pre-existing metadata), so the column can stay NULL. The namespace keeps
    governance provenance separate from the event's own metadata, and makes a
    future migration to a dedicated column a clean double-read.
    """
    if not reason_code and not metadata_json:
        return None
    merged = dict(metadata_json or {})
    if reason_code:
        existing = merged.get("_evidence")
        evidence = dict(existing) if isinstance(existing, dict) else {}
        evidence["reason_code"] = reason_code
        merged["_evidence"] = evidence
    return merged


L1_STORE_DIAGNOSTIC_EVENT_TYPES = {
    EventTypes.USER_MESSAGE,
    EventTypes.AI_RESPONSE,
    EventTypes.ACTION_EXECUTED,
}


class L1EventWriteHostProtocol(Protocol):
    event_repository: MemoryEventRepository
    _embedding_queue: Any | None
    _embedding_workers: list[asyncio.Task[None]]
    _initialized: bool
    _embedding_generation: int
    _vector_index: VectorIndex | None

    async def initialize(self, *, start_workers: bool = True) -> None: ...

    def get_search_text(self, event: MemoryEvent) -> str: ...

    def _initial_embedding_status(self, event: MemoryEvent) -> str: ...

    def _initial_embedding_profile_id(self, event: MemoryEvent) -> str | None: ...

    async def _schedule_event_embedding(self, event: MemoryEvent) -> None: ...

    async def count_events(self) -> int: ...

    def embedding_mutation_guard(self) -> Any: ...

@dataclass(slots=True)
class L1EvidenceBackfillResult:
    """Summary returned by L1 evidence annotation backfill."""

    matched: int = 0
    processed: int = 0
    updated: int = 0
    would_update: int = 0
    errors: int = 0
    dry_run: bool = False
    by_l1_retrieval_scope: dict[str, int] = field(default_factory=dict)


class L1EventWriteMixin:
    """Persist, clear, and soft-delete normalized L1 memory events."""

    async def store(self, event: MemoryEvent) -> str:
        """Persist a normalized memory event."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        self._log_store_attempt(event)
        evidence_values = self._resolve_event_evidence_values(event)
        logger.debug(
            "L1 evidence classified | event_id=%s class=%s reason=%s status=%s",
            event.event_id,
            evidence_values["evidence_class"],
            evidence_values.get("reason_code"),
            evidence_values["evidence_status"],
        )
        merged_metadata = _merge_evidence_into_metadata(
            event.metadata_json, evidence_values.get("reason_code")
        )
        calendar_timezone_id = calendar_timezone_id_from_metadata(event.metadata_json)
        if calendar_timezone_id is None:
            calendar_timezone_id = local_calendar_timezone_id()
        merged_metadata = with_calendar_timezone(
            merged_metadata,
            calendar_timezone_id=calendar_timezone_id,
        )
        result = await host.event_repository.append(EventAppend(
            event=event,
            evidence=EventEvidence(
                status=EvidenceStatus(evidence_values["evidence_status"]),
                classification=EvidenceClass(evidence_values["evidence_class"]),
                rule_version=evidence_values["evidence_rule_version"],
                retrieval_scope=L1RetrievalScope(evidence_values["l1_retrieval_scope"]),
            ),
            metadata=merged_metadata,
            embedding_status=host._initial_embedding_status(event),
            embedding_profile_id=host._initial_embedding_profile_id(event),
            search_text=host.get_search_text(event),
            source_facets=tuple(extract_source_facets(event)),
        ))
        event.session_seq = result.session_seq
        if not result.inserted:
            self._log_duplicate_event(event)
            return result.event_id
        self._log_store_success(event)
        await host._schedule_event_embedding(event)
        return result.event_id

    async def rebuild_chat_session_projection(self, session_id: str) -> None:
        """Refresh one L1 session preview after selective source deletion."""
        host = cast(L1EventWriteHostProtocol, self)
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("Chat session ID must not be empty")
        await host.initialize()
        await host.event_repository.rebuild_chat_session_projection(normalized_session_id)

    async def retire_chat_session_projection(self, session_id: str) -> None:
        """Scrub one L1 session preview after whole-session deletion."""
        host = cast(L1EventWriteHostProtocol, self)
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("Chat session ID must not be empty")
        await host.initialize()
        await host.event_repository.retire_chat_session_projection(normalized_session_id, deleted_at=time.time())

    @staticmethod
    def _log_store_attempt(event: MemoryEvent) -> None:
        if event.source == "calendar":
            if full_content_logging_enabled():
                logger.info(
                    "L1EventStore storing calendar event | "
                    "event_id=%s event_type=%s source_item_id=%s "
                    "content=%s metadata_json=%s",
                    event.event_id,
                    event.event_type,
                    event.source_item_id,
                    event.content,
                    event.metadata_json,
                )
            else:
                logger.info(
                    "L1EventStore storing calendar event | "
                    "event_id=%s event_type=%s content_chars=%d "
                    "metadata_chars=%d",
                    event.event_id,
                    event.event_type,
                    len(event.content),
                    len(event.metadata_json),
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

    @staticmethod
    def _log_duplicate_event(event: MemoryEvent) -> None:
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore skipped duplicate event | event_id=%s type=%s",
                event.event_id,
                event.event_type,
            )

    @staticmethod
    def _log_store_success(event: MemoryEvent) -> None:
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore persisted event | event_id=%s type=%s",
                event.event_id,
                event.event_type,
            )

    def _resolve_event_evidence_values(self, event: MemoryEvent) -> dict[str, Any]:
        try:
            classification = classify_event_evidence(event)
        except Exception as exc:
            logger.warning(
                "L1 evidence classification failed | event_id=%s error=%s",
                event.event_id,
                exc,
            )
            return {
                "evidence_status": int(EvidenceStatus.CLASSIFICATION_ERROR),
                "evidence_class": int(EvidenceClass.UNKNOWN),
                "evidence_rule_version": EVIDENCE_RULE_VERSION,
                "l1_retrieval_scope": int(L1RetrievalScope.NONE),
                "reason_code": None,
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
                "evidence_status": int(EvidenceStatus.POLICY_ERROR),
                "evidence_class": int(EvidenceClass.from_value(classification.evidence_class)),
                "evidence_rule_version": EVIDENCE_RULE_VERSION,
                "l1_retrieval_scope": int(L1RetrievalScope.NONE),
                "reason_code": None,
            }

        return {
            "evidence_status": int(EvidenceStatus.CLASSIFIED),
            "evidence_class": int(EvidenceClass.from_value(classification.evidence_class)),
            "evidence_rule_version": EVIDENCE_RULE_VERSION,
            "l1_retrieval_scope": int(L1RetrievalScope.from_value(policy.l1_retrieval_scope)),
            "reason_code": classification.reason_code,
        }

    async def backfill_evidence_annotations(
        self,
        *,
        user_id: str | None = None,
        source_filters: list[str] | None = None,
        event_type: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        batch_size: int = 500,
        stale_only: bool = True,
        dry_run: bool = False,
    ) -> L1EvidenceBackfillResult:
        """Classify and persist evidence policy columns for existing L1 events."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        query = EvidenceBackfillQuery(
            user_id=user_id, source_filters=tuple(source_filters or ()), event_type=event_type,
            start_time=start_time, end_time=end_time,
            stale_rule_version=EVIDENCE_RULE_VERSION if stale_only else None,
        )
        through = await host.event_repository.event_scan_high_water()
        result = L1EvidenceBackfillResult(dry_run=bool(dry_run))
        result.matched = await host.event_repository.count_evidence_backfill(query, through=through)
        after = 0
        while True:
            page = await host.event_repository.scan_evidence_backfill(
                query, after=after, through=through, limit=max(1, int(batch_size)),
            )
            if not page:
                return result
            after = page[-1].sequence
            updates: list[EvidenceAnnotationUpdate] = []
            for item in page:
                if item.record is None:
                    result.errors += 1
                    logger.warning("L1 evidence scan skipped invalid event | event_id=%s error=%s", item.event_id, item.error)
                    continue
                try:
                    values = self._resolve_event_evidence_values(item.record.event)
                    evidence = EventEvidence(
                        EvidenceStatus(values["evidence_status"]), EvidenceClass(values["evidence_class"]),
                        values["evidence_rule_version"], L1RetrievalScope(values["l1_retrieval_scope"]),
                    )
                except Exception as exc:
                    result.errors += 1
                    logger.warning("L1 evidence backfill skipped event | event_id=%s error=%s", item.event_id, exc)
                    continue
                result.processed += 1
                scope = evidence.retrieval_scope.label
                result.by_l1_retrieval_scope[scope] = result.by_l1_retrieval_scope.get(scope, 0) + 1
                if dry_run:
                    result.would_update += 1
                else:
                    updates.append(EvidenceAnnotationUpdate(item.record, evidence))
            result.updated += await host.event_repository.apply_evidence_annotations(updates)

    async def clear(
        self,
        *,
        restart_workers: bool = True,
        entity_link_clear_generation: int | None = None,
    ) -> int:
        """Clear authoritative records transactionally, then discard derived vectors."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize(start_workers=False)
        state = await host.event_repository.get_clear_state()
        if entity_link_clear_generation is None:
            if state.has_projected_links:
                raise RuntimeError("L1 clear with entity-link projections requires unified memory clear")
        elif entity_link_clear_generation <= state.entity_link_generation:
            raise RuntimeError("L1 clear must advance entity-link generation")
        host._embedding_generation += 1
        if host._embedding_queue is not None and host._embedding_workers:
            for _ in host._embedding_workers:
                await host._embedding_queue.put(None)
            await asyncio.gather(*host._embedding_workers, return_exceptions=True)
            host._embedding_workers = []
        async with host.embedding_mutation_guard():
            count = await host.event_repository.clear_events(
                entity_link_clear_generation=entity_link_clear_generation,
            )
            if host._vector_index is not None:
                await host._vector_index.clear()
        await host.initialize(start_workers=restart_workers)
        logger.info("L1 events cleared | removed=%d", count)
        return count

    async def mark_deleted(self, event_id: str, *, deleted_at: Optional[float] = None) -> bool:
        """Soft-delete an event."""
        return bool(await self.mark_deleted_many([event_id], deleted_at=deleted_at))

    async def mark_deleted_many(
        self,
        event_ids: list[str],
        *,
        deleted_at: Optional[float] = None,
    ) -> int:
        """Soft-delete a bounded set of active events and return the changed count."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        normalized = list(
            dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
        )
        if not normalized:
            return 0
        deleted_timestamp = float(deleted_at if deleted_at is not None else time.time())
        async with host.embedding_mutation_guard():
            plan = await host.event_repository.prepare_event_deletion(normalized)
            if not plan.event_ids:
                return 0
            await _delete_chunk_vectors(host, list(plan.chunk_ids))
            return await host.event_repository.soft_delete_events(
                list(plan.event_ids), deleted_at=deleted_timestamp,
            )

    async def purge_deleted_events(self, event_ids: list[str]) -> int:
        """Physically remove a bounded set of already-forgotten L1 events.

        This is a maintenance primitive for source domains that explicitly
        support replacing the same stable event identity. Product deletion
        flows must perform governed cross-layer forgetting before calling it.
        """

        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        normalized = list(
            dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
        )
        if not normalized:
            return 0
        async with host.embedding_mutation_guard():
            plan = await host.event_repository.prepare_event_deletion(normalized, only_deleted=True)
            if not plan.event_ids:
                return 0
            await _delete_chunk_vectors(host, list(plan.chunk_ids))
            return await host.event_repository.purge_deleted_events(list(plan.event_ids))

    async def list_active_event_ids_by_entity(
        self,
        entity_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_active_event_ids_by_entity(entity_id, after_event_id=after_event_id, limit=limit)

    async def list_raw_event_ids_by_entity(
        self,
        entity_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_raw_event_ids_by_entity(entity_id, after_event_id=after_event_id, limit=limit)

    async def list_active_event_ids_by_time_range(
        self,
        *,
        start: float,
        end: float,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_active_event_ids_by_time_range(start=start, end=end, after_event_id=after_event_id, limit=limit)

    async def list_raw_event_ids_by_time_range(
        self,
        *,
        start: float,
        end: float,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_raw_event_ids_by_time_range(start=start, end=end, after_event_id=after_event_id, limit=limit)

    async def list_active_event_ids_by_chat_sources(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        turn_ids: list[str] | tuple[str, ...] = (),
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_active_event_ids_by_chat_sources(user_id=user_id, session_id=session_id, turn_ids=turn_ids, after_event_id=after_event_id, limit=limit)

    async def list_raw_event_ids_by_chat_sources(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        turn_ids: list[str] | tuple[str, ...] = (),
        message_ids: list[str] | tuple[str, ...] = (),
        include_session: bool = True,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_raw_event_ids_by_chat_sources(user_id=user_id, session_id=session_id, turn_ids=turn_ids, message_ids=message_ids, include_session=include_session, after_event_id=after_event_id, limit=limit)

    async def list_active_event_ids_by_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_active_event_ids_by_chat_message(user_id=user_id, session_id=session_id, message_id=message_id, after_event_id=after_event_id, limit=limit)

    async def list_raw_event_ids_by_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        return await host.event_repository.list_raw_event_ids_by_chat_message(user_id=user_id, session_id=session_id, message_id=message_id, after_event_id=after_event_id, limit=limit)

async def _delete_chunk_vectors(
    host: L1EventWriteHostProtocol,
    chunk_ids: list[str],
) -> None:
    if host._vector_index is None:
        return
    for chunk_id in chunk_ids:
        await host._vector_index.delete_entity(entity_id=chunk_id)


__all__ = [
    "L1EvidenceBackfillResult",
    "L1EventWriteMixin",
    "L1_STORE_DIAGNOSTIC_EVENT_TYPES",
]
