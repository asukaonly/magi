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
        episodes = self._episodes(payload)
        key_events = self._key_events(payload, episodes)
        state_overlays = self._state_overlays(payload, episodes)
        return EpisodeBundleEvidence(
            episodes=episodes,
            key_events=key_events,
            state_overlays=state_overlays,
        )

    @staticmethod
    def _episodes(payload: RetrievalPayload) -> list[dict[str, Any]]:
        return [
            {
                "episode_id": ep.get("episode_id", ""),
                "label": ep.get("user_label") or ep.get("label", ""),
                "summary": ep.get("summary", ""),
                "time_start": ep.get("time_start"),
                "time_end": ep.get("time_end"),
                "dominant_mode": ep.get("dominant_mode", ""),
                "child_episodes": ep.get("child_episodes", []),
            }
            for ep in payload.l2_episodes
        ]

    def _key_events(
        self,
        payload: RetrievalPayload,
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        key_events: list[dict[str, Any]] = []
        for ep in payload.l2_episodes:
            key_events.extend(self._episode_key_events(ep))
        if not episodes and payload.l1_events:
            key_events.extend(self._fallback_key_events(payload.l1_events))
        return sorted(key_events, key=lambda e: float(e.get("timestamp", 0) or 0))

    @staticmethod
    def _episode_key_events(ep: dict[str, Any]) -> list[dict[str, Any]]:
        member_events = ep.get("member_events", [])
        anchors = [e for e in member_events if e.get("membership_role") == "anchor"]
        others = [e for e in member_events if e.get("membership_role") != "anchor"]
        ordered = anchors + sorted(
            others,
            key=lambda e: float(e.get("importance_score", 0)),
            reverse=True,
        )
        return [
            {
                "event_id": evt.get("event_id", ""),
                "summary": evt.get("summary") or evt.get("content", "")[:200],
                "timestamp": evt.get("timestamp"),
                "episode_id": ep.get("episode_id", ""),
                "membership_role": evt.get("membership_role", "member"),
                "evidence_semantics": "historical_record",
                "correction_status": evt.get("correction_status"),
            }
            for evt in ordered[:8]
        ]

    @staticmethod
    def _fallback_key_events(l1_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sorted_events = sorted(l1_events, key=lambda e: float(e.get("timestamp", 0)))
        return [
            {
                "event_id": evt.get("event_id", ""),
                "summary": evt.get("summary") or evt.get("content", "")[:200],
                "timestamp": evt.get("timestamp"),
                "episode_id": "",
                "membership_role": "fallback",
                "evidence_semantics": str(
                    evt.get("evidence_semantics") or "historical_record"
                ),
                "correction_status": evt.get("correction_status"),
            }
            for evt in sorted_events[:10]
        ]

    @staticmethod
    def _state_overlays(
        payload: RetrievalPayload,
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not episodes:
            return []
        ep_start, ep_end = EpisodeBundleAssembler._episode_time_bounds(episodes)
        state_overlays: list[dict[str, Any]] = []
        for state_fact in payload.l2_state_facts:
            inferred_at = float(state_fact.get("first_inferred_at", 0) or 0)
            expires_at = float(state_fact.get("expires_at", 0) or 0) or float("inf")
            if inferred_at <= ep_end and expires_at >= ep_start:
                state_overlays.append(
                    {
                        "trait_name": state_fact.get("trait_name", ""),
                        "trait_value": state_fact.get("trait_value", ""),
                        "confidence": float(state_fact.get("confidence_score", 0)),
                    }
                )
        return state_overlays

    @staticmethod
    def _episode_time_bounds(episodes: list[dict[str, Any]]) -> tuple[float, float]:
        return (
            min((float(ep.get("time_start", 0) or 0) for ep in episodes), default=0),
            max((float(ep.get("time_end", 0) or 0) for ep in episodes), default=0),
        )
