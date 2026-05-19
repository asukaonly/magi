"""Persistence for daily_mood_aggregate."""

from __future__ import annotations

import json
import time
from typing import List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .models import DailyMoodAggregate


class DailyMoodAggregateStore:
    """Tiny store for the sidebar mood calendar.

    Schema is created by migration 0005_daily_mood_aggregate. This store
    does not own DDL; it only reads and upserts rows.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        """Best-effort: ensure the table exists for tests that bypass migrations."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_mood_aggregate (
                    day_local_date TEXT PRIMARY KEY,
                    dominant_valence TEXT NOT NULL DEFAULT 'neutral',
                    volatility_score REAL NOT NULL DEFAULT 0.0,
                    state_curve_compact TEXT NOT NULL DEFAULT '[]',
                    event_count INTEGER NOT NULL DEFAULT 0,
                    computed_at REAL NOT NULL
                );
                """
            )
            await db.commit()

    async def upsert_aggregate(self, aggregate: DailyMoodAggregate) -> None:
        computed_at = aggregate.computed_at or time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO daily_mood_aggregate(
                    day_local_date, dominant_valence, volatility_score,
                    state_curve_compact, event_count, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(day_local_date) DO UPDATE SET
                    dominant_valence = excluded.dominant_valence,
                    volatility_score = excluded.volatility_score,
                    state_curve_compact = excluded.state_curve_compact,
                    event_count = excluded.event_count,
                    computed_at = excluded.computed_at
                """,
                (
                    aggregate.day_local_date,
                    aggregate.dominant_valence,
                    aggregate.volatility_score,
                    json.dumps(aggregate.state_curve_compact, ensure_ascii=False),
                    aggregate.event_count,
                    computed_at,
                ),
            )
            await db.commit()

    async def get_aggregate(self, *, day_local_date: str) -> Optional[DailyMoodAggregate]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM daily_mood_aggregate WHERE day_local_date = ?",
                (day_local_date,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_aggregate(row)

    async def list_aggregates(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> List[DailyMoodAggregate]:
        """Inclusive on both ends. Dates compared as ISO strings (YYYY-MM-DD)."""
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM daily_mood_aggregate
                WHERE day_local_date >= ? AND day_local_date <= ?
                ORDER BY day_local_date ASC
                """,
                (start_date, end_date),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_aggregate(r) for r in rows]

    @staticmethod
    def _row_to_aggregate(row: aiosqlite.Row) -> DailyMoodAggregate:
        return DailyMoodAggregate(
            day_local_date=str(row["day_local_date"]),
            dominant_valence=str(row["dominant_valence"]),
            volatility_score=float(row["volatility_score"]),
            state_curve_compact=json.loads(row["state_curve_compact"] or "[]"),
            event_count=int(row["event_count"]),
            computed_at=float(row["computed_at"]),
        )
