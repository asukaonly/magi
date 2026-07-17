"""Assemble cross-layer detail bundles for timeline anchors."""

from __future__ import annotations

from typing import Any

from magi.events.sensor_activity_snapshot import activity_snapshot_from_metadata

from .. import i18n as core_i18n


class TimelineContextBundleBuilder:
    """Build the right-drawer context payload for one timeline anchor."""

    def __init__(
        self,
        *,
        l1_store: Any,
        l2_store: Any | None = None,
        l3_store: Any | None = None,
        l4_store: Any | None = None,
    ) -> None:
        self._l1 = l1_store
        self._l2 = l2_store
        self._l3 = l3_store
        self._l4 = l4_store

    async def build(self, *, anchor: dict[str, Any]) -> dict[str, Any]:
        # Episode-backed anchor: use episode metadata + member events
        episode_id = anchor.get("episode_id")
        if episode_id and self._l2 is not None and hasattr(self._l2, "list_episode_events"):
            return await self._build_episode_bundle(anchor, episode_id)

        event_ids = list(
            anchor.get("representative_event_ids") or anchor.get("source_event_ids") or []
        )

        l1_events: list[dict[str, Any]] = []
        if self._l1 is not None:
            for event_id in event_ids:
                event = await self._l1.get_user_visible_event(str(event_id))
                if event is not None:
                    l1_events.append(self._to_event_preview(event))

        l2_state_evidence: list[dict[str, Any]] = []
        if self._l2 is not None:
            if hasattr(self._l2, "list_tom_assertions"):
                assertions = await self._l2.list_tom_assertions(limit=200)
                l2_state_evidence.extend(
                    assertion
                    for assertion in assertions
                    if set(assertion.get("evidence_events") or []) & set(event_ids)
                )
            if hasattr(self._l2, "find_edges_by_event_id"):
                for event_id in event_ids:
                    l2_state_evidence.extend(
                        self._with_evidence_events_alias(edge)
                        for edge in await self._l2.find_edges_by_event_id(str(event_id))
                    )

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

    async def _build_episode_bundle(
        self, anchor: dict[str, Any], episode_id: str
    ) -> dict[str, Any]:
        """Build context bundle from a durable L2 episode."""
        episode_events = await self._l2.list_episode_events(episode_id=episode_id)
        event_ids = [str(ee.get("event_id")) for ee in episode_events if ee.get("event_id")]

        l1_events: list[dict[str, Any]] = []
        if self._l1 is not None:
            for eid in event_ids:
                event = await self._l1.get_user_visible_event(eid)
                if event is not None:
                    l1_events.append(self._to_event_preview(event))

        l2_state_evidence: list[dict[str, Any]] = []
        if hasattr(self._l2, "find_edges_by_event_id"):
            for eid in event_ids[:10]:
                l2_state_evidence.extend(
                    self._with_evidence_events_alias(edge)
                    for edge in await self._l2.find_edges_by_event_id(eid)
                )

        l3_reflections: list[dict[str, Any]] = []
        if self._l3 is not None and hasattr(self._l3, "list_summaries"):
            summaries = await self._l3.list_summaries(limit=50)
            event_id_set = set(event_ids)
            l3_reflections = [
                s for s in summaries if set(s.get("source_event_ids") or []) & event_id_set
            ]

        return {
            "anchor": anchor,
            "episode_id": episode_id,
            "user_label": anchor.get("user_label"),
            "user_note": anchor.get("user_note"),
            "l1_events": l1_events,
            "l2_state_evidence": l2_state_evidence,
            "l3_reflections": l3_reflections,
            "l4_related_procedures": [],
            "chat_excerpts": [
                {"event_id": e["event_id"], "content": e["summary"]}
                for e in l1_events
                if e.get("source_type") == "chat"
            ],
            "runtime_trace": [],
        }

    def _to_event_preview(self, event: dict[str, Any]) -> dict[str, Any]:
        metadata = self._event_metadata(event)
        activity_snapshot = activity_snapshot_from_metadata(metadata)
        return {
            "event_id": str(event.get("event_id")),
            "timestamp": float(event.get("timestamp") or 0.0),
            "title": str(
                activity_snapshot.get("title")
                or event.get("event_type")
                or event.get("event_id")
                or core_i18n.t("timeline.raw_event.title", fallback="Event")
            ),
            "summary": str(activity_snapshot.get("summary") or event.get("content") or ""),
            "source_type": str(
                activity_snapshot.get("source_type") or event.get("source") or "memory"
            ),
            "source_item_id": str(
                activity_snapshot.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
                or ""
            ),
        }

    @staticmethod
    def _with_evidence_events_alias(edge: dict[str, Any]) -> dict[str, Any]:
        if "evidence_events" in edge:
            return edge
        evidence_event_ids = edge.get("evidence_event_ids")
        if not isinstance(evidence_event_ids, list):
            return edge
        return {**edge, "evidence_events": list(evidence_event_ids)}

    @staticmethod
    def _event_metadata(event: dict[str, Any]) -> dict[str, Any]:
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            return metadata
        metadata_json = event.get("metadata_json")
        if isinstance(metadata_json, dict):
            return metadata_json
        return {}
