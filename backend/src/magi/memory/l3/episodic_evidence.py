"""Build episodic evidence packs from L1 events linked to an episode."""

from __future__ import annotations

from typing import Any

from .models import EpisodicEvidenceItem, EpisodicEvidencePack


class EpisodicEvidencePackMixin:
    """Helpers for assembling EpisodicEvidencePack from L1 event rows."""

    def build_episodic_evidence_pack(
        self,
        *,
        episode: dict[str, Any],
        events: list[dict[str, Any]],
        max_events: int = 60,
    ) -> EpisodicEvidencePack:
        # Sort events by timestamp ascending so the prompt reads chronologically.
        sorted_events = sorted(
            events,
            key=lambda e: float(e.get("timestamp") or 0),
        )
        capped = sorted_events[:max_events]

        items: list[EpisodicEvidenceItem] = []
        source_event_ids: list[str] = []
        for event in capped:
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            content = str(event.get("content") or "").strip()
            if len(content) > 200:
                content = content[:200].rstrip() + "..."
            items.append(EpisodicEvidenceItem(
                event_id=event_id,
                event_type=str(event.get("event_type") or ""),
                content=content,
                timestamp=float(event["timestamp"]) if event.get("timestamp") is not None else None,
                importance_score=float(event["importance_score"]) if event.get("importance_score") is not None else None,
            ))
            source_event_ids.append(event_id)

        return EpisodicEvidencePack(
            episode_id=str(episode.get("episode_id") or ""),
            episode_type=str(episode.get("episode_type") or "activity"),
            time_start=float(episode.get("time_start") or 0),
            time_end=float(episode.get("time_end") or 0),
            primary_entity_ids=list(episode.get("primary_entity_ids") or []),
            primary_topic_keys=list(episode.get("primary_topic_keys") or []),
            source_event_count=len(items),
            source_event_ids=source_event_ids,
            events=items,
        )


__all__ = ["EpisodicEvidencePackMixin"]
