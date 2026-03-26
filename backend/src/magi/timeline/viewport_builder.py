"""Scale-aware timeline viewport assembly."""

from __future__ import annotations

import json
from typing import Any

from .cluster_builder import TimelineClusterBuilder
from .context_bundle_builder import TimelineContextBundleBuilder
from .query_interpreter import TimelineQueryInterpretation, TimelineQueryInterpreter
from .state_band_builder import TimelineStateBandBuilder


class TimelineViewportBuilder:
    """Assemble scale-aware viewport payloads from memory layers."""

    def __init__(self, *, l1_store: Any, l2_store: Any | None = None, l3_store: Any | None = None, l4_store: Any | None = None) -> None:
        self._l1 = l1_store
        self._l2 = l2_store
        self._l3 = l3_store
        self._l4 = l4_store
        self._state_band_builder = TimelineStateBandBuilder()
        self._cluster_builder = TimelineClusterBuilder()
        self._query_interpreter = TimelineQueryInterpreter()
        self._context_bundle_builder = TimelineContextBundleBuilder(
            l1_store=l1_store,
            l2_store=l2_store,
            l3_store=l3_store,
            l4_store=l4_store,
        )

    async def build_viewport(
        self,
        *,
        scale: str,
        start: float,
        end: float,
        query: str | None = None,
        timezone: str | None = None,
        focus: str = "self",
    ) -> dict[str, Any]:
        interpreted_query = self._query_interpreter.interpret(query=query, start=start, end=end)
        events = await self._load_events(start=interpreted_query.start, end=interpreted_query.end)
        summaries = await self._load_summaries()
        assertions = await self._load_assertions()
        snapshots = await self._load_snapshots()

        events = self._filter_events(events, interpreted_query)
        summaries = self._filter_summaries(summaries, interpreted_query)

        state_bands, state_markers = self._state_band_builder.build(
            start=interpreted_query.start,
            end=interpreted_query.end,
            summaries=summaries,
            assertions=assertions,
            snapshots=snapshots,
        )
        reflections = self._build_reflections(
            summaries=summaries,
            start=interpreted_query.start,
            end=interpreted_query.end,
        )
        clusters = self._cluster_builder.build(events, scale=scale) if scale in {"week", "day"} else []
        raw_events = [self._to_raw_event(event) for event in events] if scale == "hour" else []

        return {
            "viewport": {
                "scale": scale,
                "start": float(interpreted_query.start),
                "end": float(interpreted_query.end),
                "focus": focus,
                "query": query,
                "timezone": timezone,
            },
            "summary": {
                "cluster_count": len(clusters),
                "event_count": len(events),
                "dominant_modes": [cluster["dominant_mode"] for cluster in clusters[:3]],
            },
            "state_bands": state_bands,
            "state_markers": state_markers,
            "clusters": clusters,
            "reflections": reflections if scale == "month" else [],
            "raw_events": raw_events,
        }

    async def build_context_bundle(self, *, anchor: dict[str, Any]) -> dict[str, Any]:
        return await self._context_bundle_builder.build(anchor=anchor)

    async def _load_events(self, *, start: float, end: float) -> list[dict[str, Any]]:
        if self._l1 is None:
            return []
        return await self._l1.query_events(start_time=start, end_time=end, limit=500)

    async def _load_summaries(self) -> list[dict[str, Any]]:
        if self._l3 is None:
            return []
        return await self._l3.list_summaries(limit=200)

    async def _load_assertions(self) -> list[dict[str, Any]]:
        if self._l2 is None or not hasattr(self._l2, "list_tom_assertions"):
            return []
        return await self._l2.list_tom_assertions(entity_id="user:self", limit=200)

    async def _load_snapshots(self) -> list[dict[str, Any]]:
        if self._l2 is None or not hasattr(self._l2, "list_tom_snapshots"):
            return []
        return await self._l2.list_tom_snapshots(entity_id="user:self", limit=50)

    def _build_reflections(self, *, summaries: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
        reflections: list[dict[str, Any]] = []
        for summary in summaries:
            period_start = float(summary.get("period_start") or 0.0)
            period_end = float(summary.get("period_end") or period_start)
            if period_end < start or period_start > end:
                continue
            reflections.append(
                {
                    "reflection_id": str(summary.get("summary_id")),
                    "time_start": period_start,
                    "time_end": period_end,
                    "title": self._reflection_title(summary),
                    "summary": str(summary.get("content") or ""),
                    "key_topics": list(summary.get("key_topics") or []),
                    "key_entities": list(summary.get("key_entities") or []),
                    "sentiment_summary": summary.get("sentiment_summary"),
                    "change_and_pattern": summary.get("change_and_pattern"),
                    "source_summary_ids": [str(summary.get("summary_id"))],
                    "source_event_ids": list(summary.get("source_event_ids") or []),
                }
            )
        return reflections

    def _reflection_title(self, summary: dict[str, Any]) -> str:
        category = str(summary.get("summary_category") or "window")
        return f"{category.title()} Reflection"

    def _to_raw_event(self, event: dict[str, Any]) -> dict[str, Any]:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        return {
            "event_id": str(event.get("event_id")),
            "timestamp": float(event.get("timestamp") or 0.0),
            "title": str(timeline.get("title") or event.get("event_type") or event.get("event_id") or "Event"),
            "summary": str(timeline.get("summary") or event.get("content") or ""),
            "source_type": str(timeline.get("source_type") or event.get("source") or "memory"),
        }

    def _filter_events(
        self,
        events: list[dict[str, Any]],
        interpretation: TimelineQueryInterpretation,
    ) -> list[dict[str, Any]]:
        if not interpretation.has_filters:
            return events
        return [event for event in events if self._matches_text(self._event_search_text(event), interpretation)]

    def _filter_summaries(
        self,
        summaries: list[dict[str, Any]],
        interpretation: TimelineQueryInterpretation,
    ) -> list[dict[str, Any]]:
        if not interpretation.has_filters:
            return summaries
        return [summary for summary in summaries if self._matches_text(self._summary_search_text(summary), interpretation)]

    def _matches_text(self, text: str, interpretation: TimelineQueryInterpretation) -> bool:
        haystack = text.lower()

        for hint in interpretation.mood_hints:
            if not any(alias in haystack for alias in self._query_interpreter.expand_hint(hint)):
                return False

        for hint in interpretation.activity_hints:
            if not any(alias in haystack for alias in self._query_interpreter.expand_hint(hint)):
                return False

        for term in interpretation.residual_terms:
            if term not in haystack:
                return False

        return True

    @staticmethod
    def _event_search_text(event: dict[str, Any]) -> str:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        parts: list[str] = [
            str(event.get("source") or ""),
            str(event.get("content") or ""),
            str(timeline.get("title") or ""),
            str(timeline.get("summary") or ""),
            " ".join(str(tag) for tag in timeline.get("tags", []) if str(tag).strip()),
        ]
        for entity in timeline.get("entities", []):
            if isinstance(entity, dict):
                parts.extend([str(entity.get("label") or ""), str(entity.get("id") or "")])
        return " ".join(part for part in parts if part).lower()

    @staticmethod
    def _summary_search_text(summary: dict[str, Any]) -> str:
        parts: list[str] = [
            str(summary.get("content") or ""),
            " ".join(str(topic) for topic in summary.get("key_topics", []) if str(topic).strip()),
            json.dumps(summary.get("sentiment_summary") or {}, ensure_ascii=False),
            json.dumps(summary.get("change_and_pattern") or {}, ensure_ascii=False),
        ]
        for entity in summary.get("key_entities", []):
            if isinstance(entity, dict):
                parts.extend([str(entity.get("entity_id") or ""), str(entity.get("label") or "")])
            else:
                parts.append(str(entity))
        return " ".join(part for part in parts if part).lower()
