"""Event membership helpers for L2 episode persistence."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import (
    promote_source_event_entity_projection_candidates,
)
from .codec import L2EpisodeStoreBaseMixin


class L2EpisodeMembershipMixin(L2EpisodeStoreBaseMixin):
    """Manage event membership rows for L2 episodes."""

    async def add_episode_events(
        self,
        *,
        episode_id: str,
        event_ids: List[str],
        membership_role: str = "member",
        membership_confidence: float = 0.5,
        expected_status: str | None = None,
    ) -> int:
        """Add events when the episode's current status matches."""
        await self.initialize()
        now = time.time()
        added = 0
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                status_clause = "" if expected_status is None else " AND status = ?"
                status_args: tuple[Any, ...] = (
                    (episode_id,) if expected_status is None else (episode_id, str(expected_status))
                )
                async with db.execute(
                    "SELECT primary_entity_ids FROM episodes "
                    f"WHERE episode_id = ?{status_clause}",
                    status_args,
                ) as episode_cursor:
                    episode_row = await episode_cursor.fetchone()
                try:
                    decoded_primary_entity_ids = (
                        json.loads(str(episode_row[0] or "[]")) if episode_row is not None else []
                    )
                except (TypeError, json.JSONDecodeError):
                    decoded_primary_entity_ids = []
                primary_entity_ids = (
                    decoded_primary_entity_ids
                    if isinstance(decoded_primary_entity_ids, list)
                    else []
                )
                normalized_entity_ids = [
                    str(entity_id).strip()
                    for entity_id in primary_entity_ids
                    if str(entity_id).strip()
                ]

                for event_id in event_ids:
                    await promote_source_event_entity_projection_candidates(
                        db,
                        [event_id],
                        entity_ids=normalized_entity_ids,
                    )
                    if expected_status is None:
                        cursor = await db.execute(
                            """
                            INSERT OR IGNORE INTO episode_events(
                                episode_id, event_id, membership_role,
                                membership_confidence, added_at
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (episode_id, event_id, membership_role, membership_confidence, now),
                        )
                    else:
                        cursor = await db.execute(
                            """
                            INSERT OR IGNORE INTO episode_events(
                                episode_id, event_id, membership_role,
                                membership_confidence, added_at
                            )
                            SELECT ?, ?, ?, ?, ?
                            WHERE EXISTS (
                                SELECT 1 FROM episodes
                                WHERE episode_id = ? AND status = ?
                            )
                            """,
                            (
                                episode_id,
                                event_id,
                                membership_role,
                                membership_confidence,
                                now,
                                episode_id,
                                str(expected_status),
                            ),
                        )
                    added += int(cursor.rowcount > 0)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return added

    async def count_episode_events(self, *, episode_id: str) -> int:
        """Return the true distinct event membership count for an episode.

        Derived from ``episode_events`` rather than hand-summed arithmetic, so
        re-adding an already-present event (``INSERT OR IGNORE``) never inflates
        the count.
        """
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM episode_events WHERE episode_id = ?",
                (episode_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_episode_events(
        self, *, episode_id: str, limit: int = 500
    ) -> List[Dict[str, Any]]:
        """List event memberships for an episode."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM episode_events WHERE episode_id = ? ORDER BY added_at ASC LIMIT ?",
                (episode_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "episode_id": str(row["episode_id"]),
                "event_id": str(row["event_id"]),
                "membership_role": str(row["membership_role"]),
                "membership_confidence": float(row["membership_confidence"]),
                "added_at": float(row["added_at"]),
            }
            for row in rows
        ]

    async def find_episode_for_event(self, *, event_id: str) -> Optional[Dict[str, Any]]:
        """Find the episode that contains a given event."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT e.* FROM episodes e
                JOIN episode_events ee ON e.episode_id = ee.episode_id
                WHERE ee.event_id = ?
                ORDER BY e.time_start DESC
                LIMIT 1
                """,
                (event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._episode_row_to_dict(row)

    async def remove_episode_events(
        self,
        *,
        episode_id: str,
        event_ids: List[str],
        expected_status: str | None = None,
    ) -> int:
        """Remove events when the episode's current status matches."""
        if not event_ids:
            return 0
        await self.initialize()
        placeholders = ", ".join("?" for _ in event_ids)
        async with sqlite_connection_async(self.db_path) as db:
            status_clause = ""
            args: tuple[Any, ...] = (episode_id, *event_ids)
            if expected_status is not None:
                status_clause = (
                    " AND EXISTS (SELECT 1 FROM episodes "
                    "WHERE episodes.episode_id = episode_events.episode_id AND status = ?)"
                )
                args = (*args, str(expected_status))
            cursor = await db.execute(
                f"DELETE FROM episode_events WHERE episode_id = ? "
                f"AND event_id IN ({placeholders}){status_clause}",
                args,
            )
            await db.commit()
            return cursor.rowcount


__all__ = ["L2EpisodeMembershipMixin"]
