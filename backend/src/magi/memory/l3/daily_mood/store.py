"""Persistence for daily_mood_aggregate."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import (
    normalize_source_event_ids,
    source_event_time_range_block_ids,
    source_event_time_range_block_predicate,
    source_event_tombstone_ids,
)
from .models import DailyMoodAggregate

_MOOD_TRAIT_FAMILIES = {"mood", "valence"}


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
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS daily_mood_aggregate (
                    day_local_date TEXT PRIMARY KEY,
                    dominant_valence TEXT NOT NULL DEFAULT 'neutral',
                    volatility_score REAL NOT NULL DEFAULT 0.0,
                    state_curve_compact TEXT NOT NULL DEFAULT '[]',
                    event_count INTEGER NOT NULL DEFAULT 0,
                    source_event_ids TEXT NOT NULL DEFAULT '[]',
                    computed_at REAL NOT NULL
                );
                """)
            await db.commit()

    async def upsert_aggregate(self, aggregate: DailyMoodAggregate) -> bool:
        """Write one aggregate if every contributing source is still active."""
        source_event_ids = normalize_source_event_ids(aggregate.source_event_ids)
        if aggregate.event_count < 0:
            raise ValueError("Mood aggregate event_count must not be negative")
        if aggregate.event_count > 0 and not source_event_ids:
            raise ValueError("Non-empty mood aggregates require source_event_ids")
        if aggregate.event_count == 0 and source_event_ids:
            raise ValueError("Empty mood aggregates must not carry source_event_ids")
        computed_at = aggregate.computed_at or time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                if await source_event_tombstone_ids(
                    db,
                    source_event_ids,
                ) or await source_event_time_range_block_ids(db, source_event_ids):
                    await db.rollback()
                    return False
                await db.execute(
                    """
                    INSERT INTO daily_mood_aggregate(
                        day_local_date, dominant_valence, volatility_score,
                        state_curve_compact, event_count, source_event_ids,
                        computed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(day_local_date) DO UPDATE SET
                        dominant_valence = excluded.dominant_valence,
                        volatility_score = excluded.volatility_score,
                        state_curve_compact = excluded.state_curve_compact,
                        event_count = excluded.event_count,
                        source_event_ids = excluded.source_event_ids,
                        computed_at = excluded.computed_at
                    """,
                    (
                        aggregate.day_local_date,
                        aggregate.dominant_valence,
                        aggregate.volatility_score,
                        json.dumps(aggregate.state_curve_compact, ensure_ascii=False),
                        aggregate.event_count,
                        json.dumps(source_event_ids, ensure_ascii=False),
                        computed_at,
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return True

    async def forget_source_events(self, event_ids: Iterable[str]) -> int:
        """Remove mood-calendar rows derived from deleted source events.

        Claim evidence retains occurrence timestamps after L2 forgetting, so
        this remains safe to call on retries and after the claim row is
        archived. If provenance exists but can no longer be interpreted, the
        tiny projection is cleared rather than exposing stale mood data.
        """
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return 0
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                deleted = await _delete_aggregates_with_sources(
                    db,
                    event_ids=normalized,
                )
                ranges, provenance_uncertain = await _mood_ranges_for_events(
                    db,
                    event_ids=normalized,
                )
                if provenance_uncertain:
                    cursor = await db.execute("DELETE FROM daily_mood_aggregate")
                    deleted += max(int(cursor.rowcount or 0), 0)
                else:
                    deleted += await _delete_aggregate_ranges(db, ranges=ranges)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return deleted

    async def get_aggregate(self, *, day_local_date: str) -> Optional[DailyMoodAggregate]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT *
                FROM daily_mood_aggregate AS aggregate
                WHERE day_local_date = ?
                  AND {_active_aggregate_predicate("aggregate")}
                """,
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
                f"""
                SELECT * FROM daily_mood_aggregate AS aggregate
                WHERE day_local_date >= ? AND day_local_date <= ?
                  AND {_active_aggregate_predicate("aggregate")}
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
            source_event_ids=json.loads(row["source_event_ids"] or "[]"),
            computed_at=float(row["computed_at"]),
        )


def _active_aggregate_predicate(alias: str) -> str:
    return f"""
        json_valid({alias}.source_event_ids)
        AND json_type({alias}.source_event_ids) = 'array'
        AND (
            (
                {alias}.event_count = 0
                AND json_array_length({alias}.source_event_ids) = 0
            )
            OR (
                {alias}.event_count > 0
                AND json_array_length({alias}.source_event_ids) > 0
                AND NOT EXISTS (
                    SELECT 1
                    FROM json_each({alias}.source_event_ids) AS invalid_source
                    WHERE invalid_source.type != 'text'
                       OR TRIM(CAST(invalid_source.value AS TEXT)) = ''
                )
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.source_event_ids) AS source
            JOIN memory_source_event_tombstones AS tombstones
              ON tombstones.event_id = CAST(source.value AS TEXT)
        )
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.source_event_ids) AS source
            JOIN memory_projection_blocks AS projection_blocks
              ON projection_blocks.event_id = CAST(source.value AS TEXT)
             AND {source_event_time_range_block_predicate("projection_blocks")}
        )
    """


async def _delete_aggregates_with_sources(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
) -> int:
    event_json = json.dumps(event_ids, ensure_ascii=False, separators=(",", ":"))
    cursor = await db.execute(
        """
        DELETE FROM daily_mood_aggregate AS aggregate
        WHERE EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(aggregate.source_event_ids)
                    THEN aggregate.source_event_ids
                ELSE '[]'
            END) AS source
            WHERE CAST(source.value AS TEXT) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        )
        """,
        (event_json,),
    )
    return max(int(cursor.rowcount or 0), 0)


async def _mood_ranges_for_events(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
) -> tuple[list[tuple[object, object]], bool]:
    event_json = json.dumps(event_ids, ensure_ascii=False, separators=(",", ":"))
    ranges: list[tuple[object, object]] = []
    provenance_uncertain = False
    async with db.execute(
        """
        SELECT evidence.observed_from, evidence.observed_to,
               assertion.trait_family
        FROM memory_claim_evidence_events AS evidence
        LEFT JOIN tom_trait_assertions AS assertion
          ON assertion.claim_fingerprint = evidence.claim_fingerprint
        WHERE evidence.target_kind = 'assertion'
          AND evidence.event_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (event_json,),
    ) as cursor:
        ledger_rows = await cursor.fetchall()
    for observed_from, observed_to, trait_family in ledger_rows:
        if trait_family is None:
            provenance_uncertain = True
        elif str(trait_family) in _MOOD_TRAIT_FAMILIES:
            ranges.append((observed_from, observed_to))

    async with db.execute(
        """
        SELECT first_inferred_at, last_validated_at
        FROM tom_trait_assertions AS assertion
        WHERE assertion.trait_family IN ('mood', 'valence')
          AND EXISTS (
              SELECT 1
              FROM json_each(CASE
                  WHEN json_valid(assertion.evidence_events)
                      THEN assertion.evidence_events
                  ELSE '[]'
              END) AS evidence
              WHERE CAST(evidence.value AS TEXT) IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
          )
        """,
        (event_json,),
    ) as cursor:
        ranges.extend((row[0], row[1]) for row in await cursor.fetchall())
    return ranges, provenance_uncertain


async def _delete_aggregate_ranges(
    db: aiosqlite.Connection,
    *,
    ranges: list[tuple[object, object]],
) -> int:
    if not ranges:
        return 0
    date_ranges: list[tuple[str, str]] = []
    for start_value, end_value in ranges:
        try:
            start = float(start_value)
            end = float(end_value)
            if not math.isfinite(start) or not math.isfinite(end):
                raise ValueError("Non-finite mood provenance timestamp")
            start_date = datetime.fromtimestamp(min(start, end), tz=timezone.utc).date().isoformat()
            end_date = datetime.fromtimestamp(max(start, end), tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, TypeError, ValueError):
            cursor = await db.execute("DELETE FROM daily_mood_aggregate")
            return max(int(cursor.rowcount or 0), 0)
        date_ranges.append((start_date, end_date))

    async with db.execute("SELECT day_local_date FROM daily_mood_aggregate") as cursor:
        stored_dates = [str(row[0]) for row in await cursor.fetchall()]
    affected_dates = [
        day for day in stored_dates if any(start <= day <= end for start, end in date_ranges)
    ]
    if not affected_dates:
        return 0
    await db.executemany(
        "DELETE FROM daily_mood_aggregate WHERE day_local_date = ?",
        [(day,) for day in affected_dates],
    )
    return len(affected_dates)
