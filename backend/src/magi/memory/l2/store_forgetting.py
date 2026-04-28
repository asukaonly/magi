"""User-driven rejection and forgetting helpers for the L2 cognition store."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async

logger = get_logger(__name__)


class _ForgettingHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None:
        ...

    async def get_relationship(self, *, triple_id: str) -> Optional[Dict[str, Any]]:
        ...


class L2StoreForgettingMixin:
    """Apply user rejection and forgetting actions to L2 records."""

    async def reject_edge(
        self,
        *,
        triple_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark a KG edge as user-rejected."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT triple_id FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                return None
            await db.execute(
                "UPDATE knowledge_graph SET status = 'user_rejected', updated_at = ? WHERE triple_id = ?",
                (now, triple_id),
            )
            await db.commit()
        logger.info("L2 edge rejected by user", triple_id=triple_id)
        return await host.get_relationship(triple_id=triple_id)

    async def forget_entity(
        self,
        *,
        entity_id: str,
    ) -> Dict[str, int]:
        """Cascade soft-delete everything derived from an entity."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(host.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE knowledge_graph SET status = 'archived', updated_at = ?
                WHERE (subject_id = ? OR object_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, entity_id, entity_id),
            )
            counts["knowledge_graph"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions SET status = 'archived', updated_at = ?
                WHERE (entity_id = ? OR target_entity_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, entity_id, entity_id),
            )
            counts["tom_trait_assertions"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE entity_facets SET status = 'archived', updated_at = ?
                WHERE entity_id = ? AND status != 'archived'
                """,
                (now, entity_id),
            )
            counts["entity_facets"] = cursor.rowcount

            escaped = entity_id.replace('"', '""')
            pattern = f'%"{escaped}"%'
            cursor = await db.execute(
                """
                UPDATE episodes SET status = 'invalidated', updated_at = ?
                WHERE primary_entity_ids LIKE ? AND status NOT IN ('invalidated', 'archived')
                """,
                (now, pattern),
            )
            counts["episodes"] = cursor.rowcount

            await db.commit()

        logger.info("L2 entity forgotten", entity_id=entity_id, counts=counts)
        return counts

    async def forget_time_range(
        self,
        *,
        start: float,
        end: float,
    ) -> Dict[str, int]:
        """Cascade invalidation for a time range."""
        if end <= start:
            raise ValueError("end must be greater than start")

        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(host.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE episodes SET status = 'invalidated', updated_at = ?
                WHERE time_start < ? AND time_end > ? AND status NOT IN ('invalidated', 'archived')
                """,
                (now, end, start),
            )
            counts["episodes"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions SET status = 'archived', updated_at = ?
                WHERE first_inferred_at >= ? AND first_inferred_at <= ?
                  AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, start, end),
            )
            counts["tom_trait_assertions"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE knowledge_graph SET status = 'archived', updated_at = ?
                WHERE first_observed_at >= ? AND first_observed_at <= ?
                  AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, start, end),
            )
            counts["knowledge_graph"] = cursor.rowcount

            await db.commit()

        logger.info("L2 time range forgotten", start=start, end=end, counts=counts)
        return counts

    async def forget_episode(
        self,
        *,
        episode_id: str,
        delete_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Mark an episode as invalidated and optionally return member event IDs."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT episode_id FROM episodes WHERE episode_id = ?",
                (episode_id,),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                return None

            await db.execute(
                "UPDATE episodes SET status = 'invalidated', updated_at = ? WHERE episode_id = ?",
                (now, episode_id),
            )

            event_ids: list[str] = []
            if delete_events:
                async with db.execute(
                    "SELECT event_id FROM episode_events WHERE episode_id = ?",
                    (episode_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                event_ids = [str(row["event_id"]) for row in rows]

            await db.commit()

        logger.info(
            "L2 episode forgotten",
            episode_id=episode_id,
            delete_events=delete_events,
            event_count=len(event_ids),
        )
        return {"episode_id": episode_id, "event_ids": event_ids}
