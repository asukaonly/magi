"""Build clustered activity blocks for timeline viewport reads."""

from __future__ import annotations

from collections import Counter
from typing import Any


class TimelineClusterBuilder:
    """Group nearby timeline events into semantic activity blocks."""

    _MAX_GAP_BY_SCALE = {
        "month": 4.0 * 60.0 * 60.0,
        "week": 60.0 * 60.0,
        "day": 5.0 * 60.0,
        "hour": 60.0,
    }

    def build(self, events: list[dict[str, Any]], *, scale: str) -> list[dict[str, Any]]:
        if not events:
            return []
        sorted_events = sorted(events, key=lambda item: float(item.get("timestamp") or 0.0))
        groups: list[list[dict[str, Any]]] = []
        current_group: list[dict[str, Any]] = []
        max_gap = self._MAX_GAP_BY_SCALE.get(scale, 5.0 * 60.0)

        for event in sorted_events:
            if not current_group:
                current_group = [event]
                continue
            previous = current_group[-1]
            gap = float(event.get("timestamp") or 0.0) - float(previous.get("timestamp") or 0.0)
            if gap <= max_gap and self._shares_theme(previous, event):
                current_group.append(event)
                continue
            groups.append(current_group)
            current_group = [event]

        if current_group:
            groups.append(current_group)

        return [self._build_cluster(group, index) for index, group in enumerate(groups)]

    def _build_cluster(self, events: list[dict[str, Any]], index: int) -> dict[str, Any]:
        first = events[0]
        last = events[-1]
        tags = self._collect_tags(events)
        source_types = list(dict.fromkeys(str(event.get("source") or "memory") for event in events))
        label = self._resolve_label(tags, source_types)
        keywords = list(tags.keys())[:4]
        return {
            "block_id": f"cluster:{index}",
            "time_start": float(first.get("timestamp") or 0.0),
            "time_end": float(last.get("timestamp") or 0.0),
            "duration_seconds": max(0.0, float(last.get("timestamp") or 0.0) - float(first.get("timestamp") or 0.0)),
            "label": label.replace("_", " ").title(),
            "summary": self._resolve_summary(events),
            "dominant_mode": label,
            "source_types": source_types,
            "event_count": len(events),
            "representative_event_ids": [str(event.get("event_id")) for event in events[:3] if event.get("event_id")],
            "keywords": keywords,
            "media_refs": [],
            "state_snapshot": {},
        }

    def _shares_theme(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_tags = set(self._extract_tags(left))
        right_tags = set(self._extract_tags(right))
        if left_tags & right_tags:
            return True
        left_entities = set(self._extract_entity_labels(left))
        right_entities = set(self._extract_entity_labels(right))
        return bool(left_entities & right_entities)

    def _collect_tags(self, events: list[dict[str, Any]]) -> Counter[str]:
        counter: Counter[str] = Counter()
        for event in events:
            counter.update(self._extract_tags(event))
        return counter

    def _resolve_label(self, tags: Counter[str], source_types: list[str]) -> str:
        if tags:
            return tags.most_common(1)[0][0]
        if source_types:
            return source_types[0]
        return "activity"

    def _resolve_summary(self, events: list[dict[str, Any]]) -> str:
        snippets: list[str] = []
        for event in events[:2]:
            timeline = self._timeline_payload(event)
            summary = str(timeline.get("summary") or event.get("content") or "").strip()
            if summary:
                snippets.append(summary)
        return " ".join(snippets).strip()

    def _extract_tags(self, event: dict[str, Any]) -> list[str]:
        timeline = self._timeline_payload(event)
        return [str(tag).strip().lower() for tag in timeline.get("tags", []) if str(tag).strip()]

    def _extract_entity_labels(self, event: dict[str, Any]) -> list[str]:
        timeline = self._timeline_payload(event)
        entities = timeline.get("entities", [])
        labels: list[str] = []
        for entity in entities:
            if isinstance(entity, dict) and entity.get("label"):
                labels.append(str(entity["label"]).strip().lower())
        return labels

    @staticmethod
    def _timeline_payload(event: dict[str, Any]) -> dict[str, Any]:
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            timeline = metadata.get("timeline")
            if isinstance(timeline, dict):
                return timeline
        return {}

