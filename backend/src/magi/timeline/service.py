"""Timeline service facade over memory-backed viewport and context bundles."""
from __future__ import annotations

from typing import Optional

from ..events.events import Event, EventLevel
from .contracts import TimelineEvent
from .insight_pipeline import TimelineInsightPipeline
from .viewport_builder import TimelineViewportBuilder


class TimelineService:
    """Provides timeline-oriented operations over unified memory."""

    def __init__(self, unified_memory) -> None:
        self._unified_memory = unified_memory
        self._insight_pipeline = TimelineInsightPipeline(unified_memory)
        self._viewport_builder = TimelineViewportBuilder(
            l1_store=getattr(unified_memory, "l1", None),
            l2_store=getattr(unified_memory, "l2", None),
            l3_store=getattr(unified_memory, "l3", None),
            l4_store=getattr(unified_memory, "l4", None),
        )

    async def upsert_event(
        self,
        event: TimelineEvent,
        *,
        relation_candidates: Optional[list[dict]] = None,
        allowed_edge_whitelist: Optional[list[str]] = None,
    ) -> str:
        runtime_event = self._build_timeline_runtime_event(event)
        await self._unified_memory.ingest_event(
            {
                "id": event.event_id,
                "type": runtime_event.type,
                "timestamp": runtime_event.timestamp,
                "source": runtime_event.source,
                "level": runtime_event.level.value if hasattr(runtime_event.level, "value") else int(runtime_event.level),
                "correlation_id": runtime_event.correlation_id,
                "data": runtime_event.data,
                "metadata": runtime_event.metadata,
            }
        )
        event.processing_status["stored"] = True
        if relation_candidates:
            persisted = await self._insight_pipeline.process_event(
                event,
                relation_candidates,
                allowed_edge_whitelist or [],
            )
            event.processing_status["analyzed"] = True
            event.processing_status["persisted_relations"] = len(persisted)
        return event.event_id

    async def get_viewport(
        self,
        *,
        scale: str,
        start: float,
        end: float,
        query: str | None = None,
        timezone: str | None = None,
        focus: str = "self",
    ) -> dict:
        return await self._viewport_builder.build_viewport(
            scale=scale,
            start=start,
            end=end,
            query=query,
            timezone=timezone,
            focus=focus,
        )

    async def get_context_bundle(self, anchor_id: str) -> Optional[dict]:
        if getattr(self._unified_memory, "l1", None) is None:
            return None
        event = await self._unified_memory.l1.get_event(anchor_id)
        if event is not None:
            payload = self._event_to_timeline_payload(event)
            anchor = {
                "anchor_id": anchor_id,
                "anchor_type": "event",
                "title": payload["title"],
                "summary": payload["summary"],
                "representative_event_ids": [anchor_id],
            }
            return await self._viewport_builder.build_context_bundle(anchor=anchor)

        anchor = {
            "anchor_id": anchor_id,
            "anchor_type": "cluster",
            "title": anchor_id.replace(":", " ").title(),
            "summary": "",
            "representative_event_ids": [],
        }
        return await self._viewport_builder.build_context_bundle(anchor=anchor)

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
            "summary": str(timeline.get("summary") or event.get("content") or ""),
            "retention_mode": str(timeline.get("retention_mode") or event.get("retention_class") or "compressible"),
            "raw_payload_ref": timeline.get("raw_payload_ref") or metadata.get("raw_payload_ref"),
            "content_blocks": timeline.get("content_blocks") or [{"kind": "text", "value": str(event.get("content") or "")}],
            "entities": timeline.get("entities") or [],
            "tags": timeline.get("tags") or [],
            "privacy_labels": timeline.get("privacy_labels") or [],
            "processing_status": timeline.get("processing_status") or {},
            "provenance": timeline.get("provenance") or metadata,
        }
