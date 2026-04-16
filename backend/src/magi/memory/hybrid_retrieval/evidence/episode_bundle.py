"""EpisodeBundleAssembler — evidence for episode_recall mode."""

from __future__ import annotations

from typing import Any

from ..models import RetrievalPayload, RetrievalQuery
from .base import EpisodeBundleEvidence


class EpisodeBundleAssembler:
    """Assemble episode summaries + key events for narrative recall."""

    def assemble(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> EpisodeBundleEvidence:
        episodes: list[dict[str, Any]] = []
        key_events: list[dict[str, Any]] = []
        state_overlays: list[dict[str, Any]] = []

        # 1. Episodes from L2
        for ep in payload.l2_episodes:
            episodes.append({
                "episode_id": ep.get("episode_id", ""),
                "label": ep.get("user_label") or ep.get("label", ""),
                "summary": ep.get("summary", ""),
                "time_start": ep.get("time_start"),
                "time_end": ep.get("time_end"),
                "dominant_mode": ep.get("dominant_mode", ""),
                "child_episodes": ep.get("child_episodes", []),
            })

            # Key events from episode member events
            member_events = ep.get("member_events", [])
            # Prefer anchor roles, then sort by importance
            anchors = [e for e in member_events if e.get("membership_role") == "anchor"]
            others = [e for e in member_events if e.get("membership_role") != "anchor"]
            ordered = anchors + sorted(
                others,
                key=lambda e: float(e.get("importance_score", 0)),
                reverse=True,
            )
            for evt in ordered[:8]:
                key_events.append({
                    "event_id": evt.get("event_id", ""),
                    "summary": evt.get("summary") or evt.get("content", "")[:200],
                    "timestamp": evt.get("timestamp"),
                    "episode_id": ep.get("episode_id", ""),
                    "membership_role": evt.get("membership_role", "member"),
                })

        # 2. Fallback: if no episodes found, cluster L1 events by time proximity
        if not episodes and payload.l1_events:
            sorted_events = sorted(payload.l1_events, key=lambda e: float(e.get("timestamp", 0)))
            for evt in sorted_events[:10]:
                key_events.append({
                    "event_id": evt.get("event_id", ""),
                    "summary": evt.get("summary") or evt.get("content", "")[:200],
                    "timestamp": evt.get("timestamp"),
                    "episode_id": "",
                    "membership_role": "fallback",
                })

        # 3. Sort key events by timestamp for narrative order
        key_events.sort(key=lambda e: float(e.get("timestamp", 0) or 0))

        # 4. State overlays: assertions active during episode time range
        if episodes:
            ep_start = min(
                (float(ep.get("time_start", 0) or 0) for ep in episodes),
                default=0,
            )
            ep_end = max(
                (float(ep.get("time_end", 0) or 0) for ep in episodes),
                default=0,
            )
            for sf in payload.l2_state_facts:
                inferred_at = float(sf.get("first_inferred_at", 0) or 0)
                expires_at = float(sf.get("expires_at", 0) or 0) or float("inf")
                if inferred_at <= ep_end and expires_at >= ep_start:
                    state_overlays.append({
                        "trait_name": sf.get("trait_name", ""),
                        "trait_value": sf.get("trait_value", ""),
                        "confidence": float(sf.get("confidence_score", 0)),
                    })

        return EpisodeBundleEvidence(
            episodes=episodes,
            key_events=key_events,
            state_overlays=state_overlays,
        )
