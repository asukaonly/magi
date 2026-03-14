"""Timeline service facade over L1 storage."""
from __future__ import annotations

import time
import uuid
from typing import Optional

from .contracts import TimelineContentBlock, TimelineEvent
from .insight_pipeline import TimelineInsightPipeline


class TimelineService:
    """Provides timeline-oriented operations over unified memory."""

    def __init__(self, unified_memory) -> None:
        self._unified_memory = unified_memory
        self._insight_pipeline = TimelineInsightPipeline(unified_memory)

    async def upsert_event(
        self,
        event: TimelineEvent,
        *,
        relation_candidates: Optional[list[dict]] = None,
        allowed_edge_whitelist: Optional[list[str]] = None,
    ) -> str:
        await self._unified_memory.l1.store_timeline_event(event)
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

    async def get_event(self, event_id: str) -> Optional[dict]:
        return await self._unified_memory.l1.get_timeline_event(event_id)

    async def get_event_detail(self, event_id: str) -> Optional[dict]:
        event = await self.get_event(event_id)
        if event is None:
            return None
        graph_evidence = [
            edge
            for edge in await self._unified_memory.l2.find_edges_by_event_id(event_id)
        ]
        return {
            **event,
            "graph_evidence": graph_evidence,
        }

    async def list_events(self, limit: int = 100, source_type: Optional[str] = None) -> list[dict]:
        return await self._unified_memory.l1.list_timeline_events(limit=limit, source_type=source_type)

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
