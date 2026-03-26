"""Assemble cross-layer detail bundles for timeline anchors."""

from __future__ import annotations

from typing import Any


class TimelineContextBundleBuilder:
    """Build the right-drawer context payload for one timeline anchor."""

    def __init__(self, *, l1_store: Any, l2_store: Any | None = None, l3_store: Any | None = None, l4_store: Any | None = None) -> None:
        self._l1 = l1_store
        self._l2 = l2_store
        self._l3 = l3_store
        self._l4 = l4_store

    async def build(self, *, anchor: dict[str, Any]) -> dict[str, Any]:
        event_ids = list(anchor.get("representative_event_ids") or anchor.get("source_event_ids") or [])

        l1_events: list[dict[str, Any]] = []
        if self._l1 is not None:
            for event_id in event_ids:
                event = await self._l1.get_event(str(event_id))
                if event is not None:
                    l1_events.append(self._to_event_preview(event))

        l2_state_evidence: list[dict[str, Any]] = []
        if self._l2 is not None and hasattr(self._l2, "list_tom_assertions"):
            assertions = await self._l2.list_tom_assertions(entity_id="user:self", limit=50)
            l2_state_evidence = [
                assertion
                for assertion in assertions
                if set(assertion.get("evidence_events") or []) & set(event_ids)
            ]

        l3_reflections: list[dict[str, Any]] = []
        if self._l3 is not None and hasattr(self._l3, "list_summaries"):
            summaries = await self._l3.list_summaries(limit=50)
            l3_reflections = [
                summary
                for summary in summaries
                if set(summary.get("source_event_ids") or []) & set(event_ids)
            ]

        l4_related_procedures: list[dict[str, Any]] = []
        if self._l4 is not None and hasattr(self._l4, "get_all_skills"):
            l4_related_procedures = await self._l4.get_all_skills(limit=5)

        return {
            "anchor": anchor,
            "l1_events": l1_events,
            "l2_state_evidence": l2_state_evidence,
            "l3_reflections": l3_reflections,
            "l4_related_procedures": l4_related_procedures,
            "chat_excerpts": [
                {
                    "event_id": event["event_id"],
                    "content": event["summary"],
                }
                for event in l1_events
                if event.get("source_type") == "chat"
            ],
            "runtime_trace": [],
        }

    def _to_event_preview(self, event: dict[str, Any]) -> dict[str, Any]:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        return {
            "event_id": str(event.get("event_id")),
            "timestamp": float(event.get("timestamp") or 0.0),
            "title": str(timeline.get("title") or event.get("event_type") or event.get("event_id") or "Event"),
            "summary": str(timeline.get("summary") or event.get("content") or ""),
            "source_type": str(timeline.get("source_type") or event.get("source") or "memory"),
        }

