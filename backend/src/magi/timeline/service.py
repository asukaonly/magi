"""Timeline service facade over memory-backed timeline projections."""
from __future__ import annotations

import time
import uuid
from typing import Optional

from ..events.events import Event, EventLevel
from .contracts import TimelineContentBlock, TimelineEvent
from .insight_pipeline import TimelineInsightPipeline
from .projection_builder import TimelineProjectionBuilder
from .projection_models import TimelineProjectionItem, TimelineProjectionQuery
from .projection_store import TimelineProjectionStore


class TimelineService:
    """Provides timeline-oriented operations over unified memory."""

    def __init__(self, unified_memory) -> None:
        self._unified_memory = unified_memory
        self._insight_pipeline = TimelineInsightPipeline(unified_memory)
        self._projection_builder = TimelineProjectionBuilder(
            l1_store=getattr(unified_memory, "l1", None),
            l3_store=getattr(unified_memory, "l3", None),
        )
        self._projection_store: TimelineProjectionStore | None = None

    async def upsert_event(
        self,
        event: TimelineEvent,
        *,
        relation_candidates: Optional[list[dict]] = None,
        allowed_edge_whitelist: Optional[list[str]] = None,
    ) -> str:
        await self._unified_memory.ingest_event(self._build_timeline_runtime_event(event))
        event.processing_status["stored"] = True
        if relation_candidates:
            persisted = await self._insight_pipeline.process_event(
                event,
                relation_candidates,
                allowed_edge_whitelist or [],
            )
            event.processing_status["analyzed"] = True
            event.processing_status["persisted_relations"] = len(persisted)
        await self._invalidate_projection_cache()
        return event.event_id

    async def get_event(self, event_id: str) -> Optional[dict]:
        if self._unified_memory.l1 is None:
            return None
        event = await self._unified_memory.l1.get_event(event_id)
        if event is None:
            return None
        return self._event_to_timeline_payload(event)

    async def get_event_detail(self, event_id: str) -> Optional[dict]:
        event = await self.get_event(event_id)
        if event is None:
            return None
        graph_evidence = [
            edge
            for edge in await self._unified_memory.l2.find_edges_by_event_id(event_id)
        ] if getattr(self._unified_memory, "l2", None) is not None else []
        return {
            **event,
            "graph_evidence": graph_evidence,
        }

    async def list_items(
        self,
        *,
        start: float | None = None,
        end: float | None = None,
        source_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        query = TimelineProjectionQuery(
            start=start,
            end=end,
            source_type=source_type,
            limit=limit,
        )
        store = self._get_projection_store()
        cached = await store.load_items(
            window_key=query.window_key,
            filter_hash=query.filter_hash,
            projection_version=query.projection_version,
            limit=query.limit,
        )
        if cached:
            return [item.to_dict() for item in cached]

        items = await self._projection_builder.build(query)
        await store.save_items(
            window_key=query.window_key,
            filter_hash=query.filter_hash,
            projection_version=query.projection_version,
            items=items,
        )
        return [item.to_dict() for item in items]

    async def create_manual_journal(
        self,
        *,
        title: str,
        summary: str,
        text: str,
        image_refs: Optional[list[str]] = None,
    ) -> TimelineEvent:
        now = time.time()
        event = TimelineEvent(
            event_id=f"timeline_{uuid.uuid4()}",
            source_type="manual_journal",
            source_item_id=f"manual_{uuid.uuid4()}",
            occurred_at=now,
            captured_at=now,
            title=title,
            summary=summary,
            retention_mode="retain_raw",
            content_blocks=[
                TimelineContentBlock(kind="text", value=text),
                *[
                    TimelineContentBlock(kind="image", value=image_ref)
                    for image_ref in (image_refs or [])
                ],
            ],
            processing_status={"stored": True, "analyzed": False},
            provenance={"source": "manual_journal"},
        )
        await self.upsert_event(event)
        return event

    async def reanalyze_event(self, event_id: str) -> Optional[dict]:
        return await self.get_event_detail(event_id)

    def _resolve_projection_db_path(self) -> str:
        if getattr(self._unified_memory, "l3", None) is not None:
            return str(self._unified_memory.l3.db_path)
        if getattr(self._unified_memory, "l0", None) is not None:
            return str(self._unified_memory.l0.checkpoint_db_path)
        if getattr(self._unified_memory, "l1", None) is not None and getattr(self._unified_memory.l1, "db_path", None):
            return str(self._unified_memory.l1.db_path)
        raise RuntimeError("Timeline projection storage is unavailable")

    async def _invalidate_projection_cache(self) -> None:
        if self._projection_store is None:
            return
        await self._projection_store.initialize()
        await self._projection_store.clear()

    def _get_projection_store(self) -> TimelineProjectionStore:
        if self._projection_store is None:
            self._projection_store = TimelineProjectionStore(db_path=self._resolve_projection_db_path())
        return self._projection_store

    @staticmethod
    def _build_timeline_runtime_event(event: TimelineEvent) -> Event:
        payload = event.to_dict()
        return Event(
            type="TIMELINE_EVENT",
            data={
                "title": event.title,
                "summary": event.summary,
                "content_blocks": payload["content_blocks"],
                "entities": event.entities,
                "tags": event.tags,
                "source_type": event.source_type,
                "retention_mode": event.retention_mode,
                "raw_payload_ref": event.raw_payload_ref,
                "privacy_labels": event.privacy_labels,
                "processing_status": event.processing_status,
                "provenance": event.provenance,
            },
            timestamp=event.occurred_at,
            source=event.source_type,
            level=EventLevel.INFO,
            correlation_id=event.event_id,
            metadata={
                "timeline": payload,
                "raw_payload_ref": event.raw_payload_ref,
                "processing_status": event.processing_status,
            },
        )

    @staticmethod
    def _event_to_timeline_payload(event: dict) -> dict:
        metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
        timeline = metadata.get("timeline", {}) if isinstance(metadata.get("timeline"), dict) else {}
        occurred_at = float(event.get("timestamp") or event.get("created_at") or 0.0)
        return {
            "event_id": str(event["event_id"]),
            "source_type": str(timeline.get("source_type") or event.get("source") or "memory"),
            "source_item_id": str(timeline.get("source_item_id") or event.get("source_item_id") or event["event_id"]),
            "occurred_at": occurred_at,
            "captured_at": float(event.get("created_at") or occurred_at),
            "title": str(timeline.get("title") or event.get("event_type") or "Memory Event"),
            "summary": str(timeline.get("summary") or event.get("raw_content") or ""),
            "retention_mode": str(timeline.get("retention_mode") or event.get("retention_class") or "compressible"),
            "raw_payload_ref": timeline.get("raw_payload_ref") or metadata.get("raw_payload_ref"),
            "content_blocks": timeline.get("content_blocks") or [{"kind": "text", "value": str(event.get("raw_content") or "")}],
            "entities": timeline.get("entities") or [],
            "tags": timeline.get("tags") or [],
            "privacy_labels": timeline.get("privacy_labels") or [],
            "processing_status": timeline.get("processing_status") or {},
            "provenance": timeline.get("provenance") or metadata,
        }
