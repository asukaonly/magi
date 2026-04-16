"""Build clustered activity blocks for timeline viewport reads."""

from __future__ import annotations

from collections import Counter
from typing import Any


class TimelineClusterBuilder:
    """Group nearby timeline events into semantic activity blocks.

    At ``day`` and ``week`` scales the builder prefers durable episodes
    (from the L2 ``episodes`` table) over transient re-clustering when
    episodes are available.
    """

    _MAX_GAP_BY_SCALE = {
        "month": 4.0 * 60.0 * 60.0,
        "week": 60.0 * 60.0,
        "day": 5.0 * 60.0,
        "hour": 60.0,
    }

    _EPISODE_SCALES = {"day", "week"}

    def build(
        self,
        events: list[dict[str, Any]],
        *,
        scale: str,
        episodes: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        # For day/week scales, prefer durable episodes when available
        if scale in self._EPISODE_SCALES and episodes:
            clusters = [self._episode_to_cluster(ep, index) for index, ep in enumerate(episodes)]
            # Fall back: events not covered by any episode get transient clusters
            uncovered = self._uncovered_events(events, episodes)
            if uncovered:
                transient = self._cluster_events(uncovered, scale=scale, start_index=len(clusters))
                clusters.extend(transient)
            clusters.sort(key=lambda c: c["time_start"])
            return clusters

        return self._cluster_events(events, scale=scale, start_index=0)

    # ── Transient clustering (raw L1 events) ─────────────────────

    def _cluster_events(
        self,
        events: list[dict[str, Any]],
        *,
        scale: str,
        start_index: int = 0,
    ) -> list[dict[str, Any]]:
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

        return [self._build_cluster(group, start_index + index) for index, group in enumerate(groups)]

    # ── Episode-based clusters ───────────────────────────────────

    def _episode_to_cluster(self, episode: dict[str, Any], index: int) -> dict[str, Any]:
        """Convert a durable L2 episode into a cluster dict."""
        import json as _json
        time_start = float(episode.get("time_start") or 0.0)
        time_end = float(episode.get("time_end") or time_start)
        label = str(episode.get("user_label") or episode.get("label") or episode.get("episode_type") or "activity")
        summary = str(episode.get("summary") or "")
        entity_ids_raw = episode.get("primary_entity_ids") or "[]"
        if isinstance(entity_ids_raw, str):
            try:
                entity_ids_raw = _json.loads(entity_ids_raw)
            except (ValueError, TypeError):
                entity_ids_raw = []
        return {
            "block_id": f"episode:{episode.get('episode_id', index)}",
            "time_start": time_start,
            "time_end": time_end,
            "duration_seconds": max(0.0, time_end - time_start),
            "label": label.replace("_", " ").title(),
            "summary": summary,
            "dominant_mode": str(episode.get("dominant_mode") or label),
            "source_types": [],
            "event_count": int(episode.get("source_event_count") or 0),
            "representative_event_ids": [],
            "keywords": list(entity_ids_raw)[:4] if isinstance(entity_ids_raw, list) else [],
            "media_refs": [],
            "state_snapshot": {},
            "episode_id": str(episode.get("episode_id", "")),
            "user_label": episode.get("user_label"),
            "user_note": episode.get("user_note"),
        }

    @staticmethod
    def _uncovered_events(
        events: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return events that do not fall within any episode's time span."""
        uncovered: list[dict[str, Any]] = []
        for event in events:
            ts = float(event.get("timestamp") or 0.0)
            covered = any(
                float(ep.get("time_start") or 0) <= ts <= float(ep.get("time_end") or 0)
                for ep in episodes
            )
            if not covered:
                uncovered.append(event)
        return uncovered

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

