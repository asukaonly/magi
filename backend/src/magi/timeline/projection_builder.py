"""Build timeline projection items from memory layers."""

from __future__ import annotations

import time
from typing import Any

from .projection_models import TimelineProjectionItem, TimelineProjectionQuery


class TimelineProjectionBuilder:
    """Assemble event and summary items for one timeline query window."""

    def __init__(self, *, l1_store: Any, l3_store: Any | None = None) -> None:
        self._l1 = l1_store
        self._l3 = l3_store

    async def build(self, query: TimelineProjectionQuery) -> list[TimelineProjectionItem]:
        generated_at = time.time()
        items: list[TimelineProjectionItem] = []

        if self._l1 is not None:
            events = await self._l1.query_events(
                start_time=query.start,
                end_time=query.end,
                limit=max(int(query.limit), 200),
            )
            for event in events:
                if query.source_type and self._resolve_event_source_type(event) != query.source_type:
                    continue
                items.append(self._build_event_item(event, query, generated_at))

        if self._l3 is not None:
            summaries = await self._l3.list_summaries(limit=max(int(query.limit), 100))
            for summary in summaries:
                if not self._summary_overlaps(summary, query):
                    continue
                items.append(self._build_summary_item(summary, query, generated_at))

        items.sort(key=lambda item: (-item.sort_time, item.item_id))
        return items[: int(query.limit)]

    def _build_event_item(
        self,
        event: dict[str, Any],
        query: TimelineProjectionQuery,
        generated_at: float,
    ) -> TimelineProjectionItem:
        metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
        timeline_payload = metadata.get("timeline", {}) if isinstance(metadata.get("timeline"), dict) else {}
        source_type = self._resolve_event_source_type(event)
        occurred_at = float(event.get("timestamp") or event.get("created_at") or generated_at)
        title = str(
            timeline_payload.get("title")
            or self._default_event_title(event)
        )
        summary = str(
            timeline_payload.get("summary")
            or self._default_event_summary(event)
        )
        display_payload = {
            "title": title,
            "summary": summary,
            "source_type": source_type,
            "source_item_id": timeline_payload.get("source_item_id") or event.get("source_item_id"),
            "event_type": event.get("event_type"),
            "content_blocks": timeline_payload.get("content_blocks")
            or [{"kind": "text", "value": str(event.get("content") or "")}],
            "entities": timeline_payload.get("entities") or [],
            "tags": timeline_payload.get("tags") or [],
            "retention_mode": timeline_payload.get("retention_mode") or event.get("retention_class"),
            "raw_payload_ref": timeline_payload.get("raw_payload_ref")
            or metadata.get("raw_payload_ref"),
            "provenance": timeline_payload.get("provenance") or metadata,
        }
        event_id = str(event["event_id"])
        return TimelineProjectionItem(
            item_id=f"event:{event_id}",
            window_key=query.window_key,
            filter_hash=query.filter_hash,
            item_type="event",
            time_start=occurred_at,
            time_end=occurred_at,
            sort_time=occurred_at,
            primary_event_id=event_id,
            source_event_ids=[event_id],
            display_payload=display_payload,
            projection_version=query.projection_version,
            generated_at=generated_at,
        )

    def _build_summary_item(
        self,
        summary: dict[str, Any],
        query: TimelineProjectionQuery,
        generated_at: float,
    ) -> TimelineProjectionItem:
        summary_id = str(summary["summary_id"])
        period_start = float(summary["period_start"])
        period_end = float(summary["period_end"])
        display_payload = {
            "title": self._default_summary_title(summary),
            "summary": str(summary.get("content") or ""),
            "summary_type": summary.get("summary_type"),
            "summary_category": summary.get("summary_category"),
            "key_topics": summary.get("key_topics") or [],
            "key_entities": summary.get("key_entities") or [],
            "source_event_count": int(summary.get("source_event_count") or 0),
        }
        return TimelineProjectionItem(
            item_id=f"summary:{summary_id}",
            window_key=query.window_key,
            filter_hash=query.filter_hash,
            item_type="summary",
            time_start=period_start,
            time_end=period_end,
            sort_time=period_end,
            primary_summary_id=summary_id,
            source_event_ids=[str(value) for value in summary.get("source_event_ids", [])],
            source_summary_ids=[summary_id],
            display_payload=display_payload,
            projection_version=query.projection_version,
            generated_at=generated_at,
        )

    @staticmethod
    def _summary_overlaps(summary: dict[str, Any], query: TimelineProjectionQuery) -> bool:
        period_start = float(summary.get("period_start") or 0.0)
        period_end = float(summary.get("period_end") or period_start)
        if query.start is not None and period_end < float(query.start):
            return False
        if query.end is not None and period_start > float(query.end):
            return False
        return True

    @staticmethod
    def _resolve_event_source_type(event: dict[str, Any]) -> str:
        metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
        timeline_payload = metadata.get("timeline", {}) if isinstance(metadata.get("timeline"), dict) else {}
        return str(
            timeline_payload.get("source_type")
            or event.get("source")
            or "memory"
        )

    @staticmethod
    def _default_event_title(event: dict[str, Any]) -> str:
        event_type = str(event.get("event_type") or "Memory Event")
        return event_type

    @staticmethod
    def _default_event_summary(event: dict[str, Any]) -> str:
        raw = str(event.get("content") or "").strip()
        if len(raw) <= 180:
            return raw
        return f"{raw[:177].rstrip()}..."

    @staticmethod
    def _default_summary_title(summary: dict[str, Any]) -> str:
        summary_type = str(summary.get("summary_type") or "summary")
        category = str(summary.get("summary_category") or "window")
        return f"{category.title()} {summary_type.title()}"


__all__ = ["TimelineProjectionBuilder"]
