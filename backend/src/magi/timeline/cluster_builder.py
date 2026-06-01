"""Build clustered activity blocks for timeline viewport reads."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


# Tag values that just restate the source name — surfacing them as the
# cluster label would duplicate what the SourceGroup header in the day
# bucket already shows. Filter these out when deriving a label from
# event tags so we get the specific noun ("openai.com") instead of the
# bucket ("chrome_history").
_GENERIC_SOURCE_TAGS = frozenset({
    "chrome_history", "screen_time", "application_usage",
    "system_media", "manual_entry", "calendar",
})

# Episode.label values that mean "no label was actually set" and should
# trigger event-based label derivation. The default "activity" comes
# from the episodes table's DEFAULT clause when episode_formation
# couldn't infer something more specific.
_PLACEHOLDER_EPISODE_LABELS = frozenset({"", "activity"})


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
            # Bucket events per episode so _episode_to_cluster can fall
            # back to event-derived labels when the episode itself
            # carries only the default "activity" placeholder. Without
            # this the cluster row reads "—" / "activity" for every
            # Chrome/screen-time episode whose formation pass didn't
            # write a label.
            events_by_episode = self._partition_events_by_episode(events, episodes)
            clusters = [
                self._episode_to_cluster(
                    ep, index,
                    episode_events=events_by_episode.get(str(ep.get("episode_id", "")), []),
                )
                for index, ep in enumerate(episodes)
            ]
            # Fall back: events not covered by any episode get transient clusters
            uncovered = self._uncovered_events(events, episodes)
            if uncovered:
                transient = self._cluster_events(uncovered, scale=scale, start_index=len(clusters))
                clusters.extend(transient)
            clusters.sort(key=lambda c: c["time_start"])
            return clusters

        return self._cluster_events(events, scale=scale, start_index=0)

    def _partition_events_by_episode(
        self,
        events: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Map each event to ONE episode by tightest containing window.

        An event can fall inside multiple overlapping episodes; pick the
        smallest window so each event contributes to the most specific
        cluster. Ties are broken by first-listed episode.
        """
        by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            ts = float(event.get("timestamp") or 0.0)
            best_id: str | None = None
            best_window = float("inf")
            for ep in episodes:
                t0 = float(ep.get("time_start") or 0.0)
                t1 = float(ep.get("time_end") or 0.0)
                if t1 < t0:
                    continue
                if t0 <= ts <= t1 and (t1 - t0) < best_window:
                    best_id = str(ep.get("episode_id", ""))
                    best_window = t1 - t0
            if best_id is not None:
                by_episode[best_id].append(event)
        return by_episode

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

    def _episode_to_cluster(
        self,
        episode: dict[str, Any],
        index: int,
        *,
        episode_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Convert a durable L2 episode into a cluster dict.

        ``episode_events`` is the subset of L1 events whose timestamps
        fall in this episode's window. Used to derive a meaningful label
        when the episode itself only has the default "activity"
        placeholder — pulls metadata.timeline.tags off the events and
        promotes the top specific tag (e.g. a Chrome cluster's domain).
        Pass None / [] to skip enrichment and fall through to the
        original episode_type fallback.
        """
        import json as _json
        time_start = float(episode.get("time_start") or 0.0)
        time_end = float(episode.get("time_end") or time_start)
        raw_user_label = str(episode.get("user_label") or "").strip()
        raw_label = str(episode.get("label") or "").strip()
        if raw_user_label:
            label_display = raw_user_label
            label_raw = raw_user_label
        elif raw_label and raw_label.lower() not in _PLACEHOLDER_EPISODE_LABELS:
            label_display = raw_label.replace("_", " ").title()
            label_raw = raw_label
        else:
            # Episode itself has no useful label. Try to derive one from
            # the events that fall in its window before settling for the
            # episode_type / "activity" fallback. Derived labels are
            # usually already in display form (e.g. "openai.com") so
            # they bypass the snake_case title-casing that mangles
            # domain-shaped strings into "Openai.Com".
            derived = self._derive_label_from_events(episode_events or [])
            if derived:
                label_display = derived
                label_raw = derived
            else:
                episode_type = str(episode.get("episode_type") or "activity")
                label_display = episode_type.replace("_", " ").title()
                label_raw = episode_type
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
            "label": label_display,
            "summary": summary,
            "dominant_mode": str(episode.get("dominant_mode") or label_raw),
            "source_types": [],
            "event_count": int(episode.get("source_event_count") or 0),
            "representative_event_ids": [],
            "keywords": list(entity_ids_raw)[:4] if isinstance(entity_ids_raw, list) else [],
            "media_refs": [],
            "state_snapshot": {},
            "episode_id": str(episode.get("episode_id", "")),
            "user_label": episode.get("user_label"),
            "user_note": episode.get("user_note"),
            "user_pinned": bool(episode.get("user_pinned")),
            # Plan 1+2 immersive fields, surfaced for the frontend
            "slice_narrative": str(episode.get("slice_narrative") or ""),
            "slice_sensory_detail": str(episode.get("slice_sensory_detail") or ""),
            "representative_asset_ref": str(episode.get("representative_asset_ref") or ""),
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

    def _derive_label_from_events(self, events: list[dict[str, Any]]) -> str:
        """Synthesize a short label from the events in a cluster.

        Used when the episode itself doesn't carry a meaningful label.
        Counts metadata.timeline.tags across the events, drops the
        generic source-name tags (which would duplicate the SourceGroup
        header), and surfaces the top 1–2 specific tags joined with '、'.

        Returns empty string when no specific tags survive the filter —
        caller falls back to the episode_type / "activity" default.

        Examples (input events tagged via Chrome sensor):
          - 8 events all tagged ["chrome_history", "openai.com"]
              → "openai.com"
          - mixed ["chrome_history", "openai.com"] and
                  ["chrome_history", "anthropic.com"]
              → "openai.com、anthropic.com"
          - only ["chrome_history"] tags (sensor didn't set domain)
              → "" (caller uses episode_type fallback)
        """
        if not events:
            return ""
        # _extract_tags already lowercases; the original casing is lost
        # here. For domain-style tags this is fine ("openai.com" reads
        # the same lowercase); for human-name tags it's a small loss
        # we accept for code simplicity.
        counter: Counter[str] = Counter()
        for event in events:
            for tag in self._extract_tags(event):
                if tag and tag not in _GENERIC_SOURCE_TAGS:
                    counter[tag] += 1
        if not counter:
            return ""
        top = [tag for tag, _ in counter.most_common(2)]
        return "、".join(top)

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

