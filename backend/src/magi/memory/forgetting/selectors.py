"""Bounded event enumeration for durable forget selectors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.sqlite import sqlite_connection_async
from .models import ForgetSelector, SelectedEvent


@dataclass(frozen=True, slots=True)
class ProjectionSelection:
    block_kind: str
    target_id: str
    scope: str


class ForgetSelectorResolver:
    """Enumerate raw source rows and durable projection barriers."""

    def __init__(self, *, memory_db_path: str, l1: Any) -> None:
        self._memory_db_path = memory_db_path
        self._l1 = l1

    async def list_event_page(
        self,
        selector: ForgetSelector,
        *,
        after_event_id: str,
        limit: int,
    ) -> list[SelectedEvent]:
        page_size = max(1, min(int(limit), 1000))
        payload = selector.payload
        event_ids: list[str]
        if selector.kind == "known_events":
            event_ids = [
                str(event_id)
                for event_id in payload.get("event_ids", [])
                if str(event_id) > after_event_id
            ][:page_size]
        elif selector.kind == "entity":
            if not payload.get("delete_l1_events") or self._l1 is None:
                return []
            event_ids = await self._list_entity_source_events(
                entity_id=str(payload["entity_id"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
        elif selector.kind == "time_range":
            if not payload.get("delete_l1_events") or self._l1 is None:
                return []
            event_ids = await self._l1.list_raw_event_ids_by_time_range(
                start=float(payload["start"]),
                end=float(payload["end"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
        elif selector.kind == "episode":
            if not payload.get("delete_events"):
                return []
            event_ids = await self._list_episode_events(
                episode_id=str(payload["episode_id"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
        elif selector.kind == "chat_session":
            if self._l1 is None:
                return []
            event_ids = await self._l1.list_raw_event_ids_by_chat_sources(
                user_id=str(payload["user_id"]),
                session_id=str(payload["session_id"]),
                turn_ids=tuple(str(item) for item in payload.get("turn_ids", [])),
                include_session=True,
                after_event_id=after_event_id,
                limit=page_size,
            )
        elif selector.kind == "chat_history":
            if self._l1 is None:
                return []
            event_ids = await self._l1.list_raw_event_ids_by_chat_sources(
                user_id=str(payload["user_id"]),
                session_id=str(payload["session_id"]),
                turn_ids=tuple(str(item) for item in payload.get("turn_ids", [])),
                message_ids=tuple(
                    str(item.get("message_id") or "")
                    for item in payload.get("messages", [])
                    if isinstance(item, dict)
                ),
                include_session=False,
                after_event_id=after_event_id,
                limit=page_size,
            )
        elif selector.kind == "chat_message":
            if self._l1 is None:
                return []
            event_ids = await self._l1.list_raw_event_ids_by_chat_message(
                user_id=str(payload["user_id"]),
                session_id=str(payload["session_id"]),
                message_id=str(payload["message_id"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
        else:
            raise ValueError(f"Unsupported forget selector: {selector.kind}")
        return await self._selected_events(event_ids)

    def projection_selections(
        self,
        selector: ForgetSelector,
    ) -> tuple[ProjectionSelection, ...]:
        """Return every old-evidence projection barrier owned by a selector."""
        if selector.kind == "entity":
            entity_id = str(selector.payload["entity_id"])
            return (
                ProjectionSelection("entity_projection", entity_id, "entity_evidence"),
                ProjectionSelection(
                    "entity_projection_candidate",
                    entity_id,
                    "entity_backlog",
                ),
                ProjectionSelection(
                    "episode_formation",
                    f"entity:{entity_id}",
                    "entity_episodes",
                ),
            )
        if selector.kind == "time_range":
            return (
                ProjectionSelection(
                    "episode_formation",
                    f"time:{selector.selector_hash}",
                    "time_range",
                ),
            )
        if selector.kind == "episode":
            return (
                ProjectionSelection(
                    "episode_formation",
                    str(selector.payload["episode_id"]),
                    "episode",
                ),
            )
        return ()

    async def list_projection_event_page(
        self,
        selector: ForgetSelector,
        *,
        scope: str,
        after_event_id: str,
        limit: int,
        created_before: float | None = None,
    ) -> list[str]:
        page_size = max(1, min(int(limit), 1000))
        if selector.kind == "entity" and scope == "entity_evidence":
            return await self._list_entity_source_events(
                entity_id=str(selector.payload["entity_id"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
        if selector.kind == "entity" and scope == "entity_backlog":
            return await self._list_entity_backlog_events(
                after_event_id=after_event_id,
                limit=page_size,
                created_before=created_before,
            )
        if selector.kind == "entity" and scope == "entity_episodes":
            return await self._list_entity_episode_events(
                entity_id=str(selector.payload["entity_id"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
        if selector.kind == "time_range" and scope == "time_range":
            payload = selector.payload
            l1_ids = (
                await self._l1.list_raw_event_ids_by_time_range(
                    start=float(payload["start"]),
                    end=float(payload["end"]),
                    after_event_id=after_event_id,
                    limit=page_size,
                )
                if self._l1 is not None
                else []
            )
            durable_ids = await self._list_time_range_evidence_events(
                start=float(payload["start"]),
                end=float(payload["end"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
            return sorted(set(l1_ids).union(durable_ids))[:page_size]
        if selector.kind == "episode" and scope == "episode":
            return await self._list_episode_events(
                episode_id=str(selector.payload["episode_id"]),
                after_event_id=after_event_id,
                limit=page_size,
            )
        return []

    async def _list_entity_source_events(
        self,
        *,
        entity_id: str,
        after_event_id: str,
        limit: int,
    ) -> list[str]:
        """Return every source known to support an entity in stable key order."""
        page_size = max(1, min(int(limit), 1000))
        l1_ids = (
            await self._l1.list_raw_event_ids_by_entity(
                entity_id,
                after_event_id=after_event_id,
                limit=page_size,
            )
            if self._l1 is not None
            else []
        )
        durable_ids = await self._list_entity_evidence_events(
            entity_id=entity_id,
            after_event_id=after_event_id,
            limit=page_size,
        )
        return sorted(set(l1_ids).union(durable_ids))[:page_size]

    @staticmethod
    def event_reference_options(selector: ForgetSelector) -> tuple[bool, bool]:
        """Return include-turn and source-item replay policies."""
        if selector.kind == "known_events":
            return (
                bool(selector.payload.get("include_turn_references", True)),
                bool(selector.payload.get("block_source_item", True)),
            )
        return True, True

    async def episode_exists(self, episode_id: str) -> bool:
        async with sqlite_connection_async(self._memory_db_path) as db:
            async with db.execute(
                "SELECT 1 FROM episodes WHERE episode_id = ? LIMIT 1",
                (str(episode_id),),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def _selected_events(self, event_ids: list[str]) -> list[SelectedEvent]:
        if not event_ids:
            return []
        states = (
            await self._l1.get_raw_event_active_states(event_ids) if self._l1 is not None else {}
        )
        return [
            SelectedEvent(event_id=event_id, was_active=bool(states.get(event_id, False)))
            for event_id in event_ids
        ]

    async def _list_episode_events(
        self,
        *,
        episode_id: str,
        after_event_id: str,
        limit: int,
    ) -> list[str]:
        async with sqlite_connection_async(self._memory_db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT event_id
                FROM episode_events
                WHERE episode_id = ? AND event_id > ?
                ORDER BY event_id
                LIMIT ?
                """,
                (episode_id, after_event_id, max(1, min(int(limit), 1000))),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def _list_entity_evidence_events(
        self,
        *,
        entity_id: str,
        after_event_id: str,
        limit: int,
    ) -> list[str]:
        async with sqlite_connection_async(self._memory_db_path) as db:
            async with db.execute(
                """
                SELECT event_id FROM (
                    SELECT evidence.event_id AS event_id
                    FROM memory_claim_evidence_events AS evidence
                    JOIN tom_trait_assertions AS assertion
                      ON evidence.target_kind = 'assertion'
                     AND evidence.claim_fingerprint = assertion.claim_fingerprint
                    WHERE assertion.entity_id = ? OR assertion.target_entity_id = ?
                    UNION
                    SELECT evidence.event_id
                    FROM memory_claim_evidence_events AS evidence
                    JOIN knowledge_graph AS edge
                      ON evidence.target_kind = 'edge'
                     AND evidence.claim_fingerprint = edge.claim_fingerprint
                    WHERE edge.subject_id = ? OR edge.object_id = ?
                    UNION
                    SELECT name.event_id
                    FROM entity_name_evidence AS name
                    WHERE name.entity_id = ?
                    UNION
                    SELECT CAST(source.value AS TEXT)
                    FROM entity_mentions AS mention,
                         json_each(CASE
                             WHEN json_valid(mention.evidence_event_ids)
                                 THEN mention.evidence_event_ids ELSE '[]'
                         END) AS source
                    WHERE mention.resolved_entity_id = ?
                    UNION
                    SELECT CAST(source.value AS TEXT)
                    FROM entity_facets AS facet,
                         json_each(CASE
                             WHEN json_valid(facet.evidence_event_ids)
                                 THEN facet.evidence_event_ids ELSE '[]'
                         END) AS source
                    WHERE facet.entity_id = ?
                    UNION
                    SELECT member.event_id
                    FROM episode_events AS member
                    JOIN episodes AS episode ON episode.episode_id = member.episode_id
                    WHERE ? IN (
                        SELECT CAST(value AS TEXT)
                        FROM json_each(CASE
                            WHEN json_valid(episode.primary_entity_ids)
                                THEN episode.primary_entity_ids ELSE '[]'
                        END)
                    )
                )
                WHERE event_id > ?
                ORDER BY event_id
                LIMIT ?
                """,
                (
                    entity_id,
                    entity_id,
                    entity_id,
                    entity_id,
                    entity_id,
                    entity_id,
                    entity_id,
                    entity_id,
                    after_event_id,
                    limit,
                ),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def _list_entity_backlog_events(
        self,
        *,
        after_event_id: str,
        limit: int,
        created_before: float | None,
    ) -> list[str]:
        """Return old unfinished jobs under a target-scoped entity barrier."""
        projection_cutoff = float(created_before) if created_before is not None else float("inf")
        async with sqlite_connection_async(self._memory_db_path) as db:
            async with db.execute(
                """
                SELECT event_id
                FROM l2_projection_jobs
                WHERE status IN ('pending', 'queued', 'running')
                  AND created_at <= ?
                  AND event_id > ?
                ORDER BY event_id
                LIMIT ?
                """,
                (projection_cutoff, after_event_id, limit),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def _list_entity_episode_events(
        self,
        *,
        entity_id: str,
        after_event_id: str,
        limit: int,
    ) -> list[str]:
        async with sqlite_connection_async(self._memory_db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT member.event_id
                FROM episode_events AS member
                JOIN episodes AS episode ON episode.episode_id = member.episode_id
                WHERE member.event_id > ?
                  AND ? IN (
                      SELECT CAST(value AS TEXT)
                      FROM json_each(CASE
                          WHEN json_valid(episode.primary_entity_ids)
                              THEN episode.primary_entity_ids ELSE '[]'
                      END)
                  )
                ORDER BY member.event_id
                LIMIT ?
                """,
                (after_event_id, entity_id, limit),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def _list_time_range_evidence_events(
        self,
        *,
        start: float,
        end: float,
        after_event_id: str,
        limit: int,
    ) -> list[str]:
        async with sqlite_connection_async(self._memory_db_path) as db:
            async with db.execute(
                """
                SELECT event_id FROM (
                    SELECT event_id
                    FROM memory_claim_evidence_events
                    WHERE observed_to >= ? AND observed_from <= ?
                    UNION
                    SELECT member.event_id
                    FROM episode_events AS member
                    JOIN episodes AS episode ON episode.episode_id = member.episode_id
                    WHERE episode.time_start <= ? AND episode.time_end >= ?
                )
                WHERE event_id > ?
                ORDER BY event_id
                LIMIT ?
                """,
                (start, end, end, start, after_event_id, limit),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]


__all__ = ["ForgetSelectorResolver", "ProjectionSelection"]
