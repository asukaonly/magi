"""Cluster presentation enrichment for timeline viewports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .state_band_builder import derive_state_from_tone
from .viewport_i18n import is_zh_locale, source_label


@dataclass(frozen=True)
class EpisodeClusterSourceDetails:
    source_types: list[str]
    media_refs: list[str]
    mood: str | None


class TimelineClusterPresentationBuilder:
    """Apply viewport-only presentation enrichment to cluster records."""

    def prepare(
        self,
        clusters: list[dict[str, Any]],
        *,
        events: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
        start: float,
        end: float,
        locale: str,
    ) -> list[dict[str, Any]]:
        if not clusters:
            return clusters
        self._localize_labels(clusters, locale=locale)
        self._enrich_states(clusters, summaries, start=start, end=end)
        self._enrich_source_types(clusters, events)
        return clusters

    def _enrich_states(
        self,
        clusters: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
        *,
        start: float,
        end: float,
    ) -> None:
        relevant = self._relevant_summaries(summaries, start=start, end=end)
        for cluster in clusters:
            state_snapshot = self._state_snapshot_for_cluster(cluster, relevant)
            if state_snapshot:
                cluster["state_snapshot"] = state_snapshot

    @staticmethod
    def _relevant_summaries(
        summaries: list[dict[str, Any]],
        *,
        start: float,
        end: float,
    ) -> list[dict[str, Any]]:
        return [
            summary
            for summary in summaries
            if float(summary.get("period_end") or 0) >= start
            and float(summary.get("period_start") or 0) <= end
        ]

    @staticmethod
    def _state_snapshot_for_cluster(
        cluster: dict[str, Any],
        summaries: list[dict[str, Any]],
    ) -> dict[str, float]:
        cluster_start = cluster["time_start"]
        cluster_end = cluster["time_end"]
        for summary in summaries:
            period_start = float(summary.get("period_start") or 0)
            period_end = float(summary.get("period_end") or period_start)
            if period_end < cluster_start or period_start > cluster_end:
                continue
            sentiment = summary.get("sentiment_summary")
            if not isinstance(sentiment, dict):
                break
            tone = str(sentiment.get("tone") or "").strip()
            if tone:
                return derive_state_from_tone(tone)
            break
        return {}

    def _enrich_source_types(
        self,
        clusters: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> None:
        for cluster in clusters:
            if not self._is_episode_cluster(cluster):
                continue
            details = self._episode_source_details(cluster, events)
            if not details.source_types:
                continue
            cluster["source_types"] = details.source_types
            if details.media_refs:
                cluster["media_refs"] = details.media_refs
            if details.mood:
                cluster["mood"] = details.mood

    @staticmethod
    def _is_episode_cluster(cluster: dict[str, Any]) -> bool:
        block_id = str(cluster.get("block_id") or "")
        if not block_id.startswith("episode:"):
            return False
        time_start = float(cluster.get("time_start") or 0.0)
        time_end = float(cluster.get("time_end") or 0.0)
        return time_end > time_start

    def _episode_source_details(
        self,
        cluster: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> EpisodeClusterSourceDetails:
        time_start = float(cluster.get("time_start") or 0.0)
        time_end = float(cluster.get("time_end") or 0.0)
        counts: Counter[str] = Counter()
        attachments: list[str] = []
        mood: str | None = None
        for event in events:
            event_time = float(event.get("timestamp") or 0.0)
            if not (time_start <= event_time <= time_end):
                continue
            source = str(event.get("source") or "").strip()
            if source:
                counts[source] += 1
            if source == "manual_entry":
                refs, mood = self._manual_entry_details(event, existing_mood=mood)
                attachments.extend(refs)
        return EpisodeClusterSourceDetails(
            source_types=self._ordered_source_types(counts),
            media_refs=self._dedupe_refs(attachments),
            mood=mood,
        )

    @staticmethod
    def _manual_entry_details(
        event: dict[str, Any],
        *,
        existing_mood: str | None,
    ) -> tuple[list[str], str | None]:
        metadata = event.get("metadata") or event.get("metadata_json") or {}
        if not isinstance(metadata, dict):
            return [], existing_mood
        manual_meta = metadata.get("manual_entry") or {}
        if not isinstance(manual_meta, dict):
            return [], existing_mood
        refs = [ref for ref in manual_meta.get("attachments") or [] if isinstance(ref, str) and ref]
        mood = existing_mood
        if not mood and isinstance(manual_meta.get("mood"), str):
            mood = manual_meta["mood"]
        return refs, mood

    @staticmethod
    def _ordered_source_types(counts: Counter[str]) -> list[str]:
        ordered = [source for source, _ in counts.most_common()]
        if "manual_entry" in ordered and ordered[0] != "manual_entry":
            ordered.remove("manual_entry")
            ordered.insert(0, "manual_entry")
        return ordered

    @staticmethod
    def _dedupe_refs(refs: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for ref in refs:
            if ref not in seen:
                seen.add(ref)
                deduped.append(ref)
        return deduped

    def _localize_labels(self, clusters: list[dict[str, Any]], *, locale: str) -> None:
        if not is_zh_locale(locale):
            return
        for cluster in clusters:
            label = str(cluster.get("label") or "").strip()
            if not label:
                continue
            source_candidates = [str(cluster.get("dominant_mode") or "")]
            source_candidates.extend(str(source) for source in cluster.get("source_types") or [])
            for source in source_candidates:
                if self._is_generated_source_label(label, source):
                    cluster["label"] = source_label(source, locale)
                    break

    @classmethod
    def _is_generated_source_label(cls, label: str, source_type: str) -> bool:
        normalized_label = cls._normalize_display_text(label)
        normalized_source = cls._normalize_display_text(source_type)
        return bool(normalized_label and normalized_label == normalized_source)

    @staticmethod
    def _normalize_display_text(value: Any) -> str:
        return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).lower()
