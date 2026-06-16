"""Event membership helpers for L2 episode persistence."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
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
    ) -> int:
        """Add events to an episode. Returns the number of new memberships."""
        await self.initialize()
        now = time.time()
        added = 0
        async with sqlite_connection_async(self.db_path) as db:
            for event_id in event_ids:
                try:
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO episode_events(
                            episode_id, event_id, membership_role, membership_confidence, added_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (episode_id, event_id, membership_role, membership_confidence, now),
                    )
                    added += 1
                except Exception:
                    pass
            await db.commit()
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
        self, *, episode_id: str, event_ids: List[str]
    ) -> int:
        """Remove events from an episode. Returns the count removed."""
        if not event_ids:
            return 0
        await self.initialize()
        placeholders = ", ".join("?" for _ in event_ids)
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"DELETE FROM episode_events WHERE episode_id = ? AND event_id IN ({placeholders})",
                (episode_id, *event_ids),
            )
            await db.commit()
            return cursor.rowcount


__all__ = ["L2EpisodeMembershipMixin"]
