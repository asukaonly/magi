"""FTS helpers for L2 episode persistence."""

from __future__ import annotations

from typing import Any, Dict, List

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..assertions.state_machine import RETRIEVAL_EXCLUDED_STATUSES
from .codec import L2EpisodeStoreBaseMixin


class L2EpisodeFtsMixin(L2EpisodeStoreBaseMixin):
    """Index and search episode full-text content."""

    async def index_episode_fts(
        self, *, episode_id: str, summary: str, label: str, user_label: str
    ) -> None:
        """Insert or replace FTS content for an episode."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                "DELETE FROM episodes_fts WHERE episode_id = ?",
                (episode_id,),
            )
            await db.execute(
                "INSERT INTO episodes_fts(episode_id, summary, label, user_label) VALUES(?, ?, ?, ?)",
                (episode_id, summary or "", label or "", user_label or ""),
            )
            await db.commit()

    async def search_episodes_fts(
        self, *, query: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Full-text search over episode summary/label/user_label.

        Terms are OR-combined: quoting the whole query as a single phrase
        would require all terms to appear adjacently, which kills recall
        for multi-term queries (e.g. entity names joined by spaces).
        """
        await self.initialize()
        terms = [term for term in query.split() if term.strip()]
        if not terms:
            return []
        match_expression = " OR ".join(
            '"{}"'.format(term.replace('"', '""')) for term in terms
        )
        status_ph = ", ".join("?" for _ in RETRIEVAL_EXCLUDED_STATUSES)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT e.* FROM episodes e
                JOIN episodes_fts f ON e.episode_id = f.episode_id
                WHERE episodes_fts MATCH ?
                  AND e.status NOT IN ({status_ph})
                ORDER BY rank
                LIMIT ?
                """,
                (match_expression, *RETRIEVAL_EXCLUDED_STATUSES, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._episode_row_to_dict(row) for row in rows]


__all__ = ["L2EpisodeFtsMixin"]
