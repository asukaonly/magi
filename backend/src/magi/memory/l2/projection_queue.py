"""Durable projection job queue for L2 cognition pipeline.

Manages the lifecycle of event projection jobs:
pending → queued → running → completed/failed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async

DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD = 300
DEFAULT_L2_STEADY_STATE_MAX_WAIT_SECONDS = 45.0

logger = get_logger(__name__)


class ProjectionJobQueue:
    """Persistent queue for L2 extraction projection jobs.

    Shares the same SQLite database as ``L2CognitionStore`` but owns
    all logic for the ``l2_projection_jobs`` table exclusively.
    """

    def __init__(self, *, db_path: str) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def ensure_schema(self, db: aiosqlite.Connection) -> None:
        """Add any missing columns to the projection jobs table (migrations)."""
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(l2_projection_jobs)") as cursor:
            rows = await cursor.fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        required_columns = {
            "catch_up_owner": "TEXT",
            "max_events": "INTEGER",
            "min_ready_events": "INTEGER",
            "max_wait_seconds": "REAL",
            "started_at": "REAL",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            await db.execute(f"ALTER TABLE l2_projection_jobs ADD COLUMN {column_name} {column_type}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        *,
        event_id: str,
        source: str,
        event_type: str,
        batch_owner: str | None = None,
        catch_up_owner: str | None = None,
        max_events: int | None = None,
        min_ready_events: int | None = None,
        max_wait_seconds: float | None = None,
    ) -> bool:
        """Insert one pending projection job if it does not already exist."""
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO l2_projection_jobs(
                    event_id,
                    source,
                    event_type,
                    batch_owner,
                    catch_up_owner,
                    max_events,
                    min_ready_events,
                    max_wait_seconds,
                    status,
                    attempt_count,
                    claimed_by,
                    claimed_at,
                    started_at,
                    completed_at,
                    last_error,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (
                    event_id,
                    source,
                    event_type,
                    batch_owner,
                    catch_up_owner,
                    max_events,
                    min_ready_events,
                    max_wait_seconds,
                    now,
                    now,
                ),
            )
            await db.commit()
        return bool(cursor.rowcount)

    async def claim_ready(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim pending jobs whose owner bucket is ready for extraction."""
        requested_limit = max(1, int(limit))
        now = time.time()
        selected_event_ids: list[str] = []
        effective_owner_by_event_id: dict[str, str] = {}

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            remaining = requested_limit
            pending_total = await self._count_by_status(db, "pending")
            claim_mode = "catch_up" if pending_total >= DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD else "steady_state"

            async with db.execute(
                """
                SELECT event_id
                FROM l2_projection_jobs
                WHERE status = 'pending'
                  AND (batch_owner IS NULL OR batch_owner = '')
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (remaining,),
            ) as cursor:
                rows = await cursor.fetchall()
            selected_event_ids.extend(str(row["event_id"]) for row in rows)
            remaining -= len(rows)

            if remaining > 0:
                async with db.execute(
                    """
                    SELECT
                        batch_owner,
                        MIN(NULLIF(catch_up_owner, '')) AS bucket_catch_up_owner,
                        COUNT(*) AS pending_count,
                        MIN(created_at) AS oldest_created_at,
                        MIN(CASE WHEN max_events IS NOT NULL AND max_events > 0 THEN max_events END) AS bucket_max_events,
                        MIN(CASE WHEN min_ready_events IS NOT NULL AND min_ready_events > 0 THEN min_ready_events END) AS bucket_min_ready_events,
                        MIN(CASE WHEN max_wait_seconds IS NOT NULL AND max_wait_seconds > 0 THEN max_wait_seconds END) AS bucket_max_wait_seconds
                    FROM l2_projection_jobs
                    WHERE status = 'pending'
                      AND batch_owner IS NOT NULL
                      AND batch_owner != ''
                    GROUP BY batch_owner
                    ORDER BY oldest_created_at ASC
                    """,
                ) as cursor:
                    owner_rows = await cursor.fetchall()

                low_frequency_owners_by_tail: dict[str, list[aiosqlite.Row]] = {}
                for owner_row in owner_rows:
                    if remaining <= 0:
                        break
                    owner = str(owner_row["batch_owner"] or "").strip()
                    if not owner:
                        continue
                    pending_count = int(owner_row["pending_count"] or 0)
                    if pending_count <= 0:
                        continue
                    max_events_value = owner_row["bucket_max_events"]
                    max_events = int(max_events_value or 1)
                    min_ready_value = owner_row["bucket_min_ready_events"]
                    min_ready_events = int(min_ready_value or max_events)
                    max_wait_value = owner_row["bucket_max_wait_seconds"]
                    catch_up_owner = str(owner_row["bucket_catch_up_owner"] or "").strip()
                    oldest_created_at = float(owner_row["oldest_created_at"] or now)
                    oldest_age_seconds = max(0.0, now - oldest_created_at)

                    effective_ready_events = max_events
                    effective_wait_seconds = float(max_wait_value) if max_wait_value is not None else None
                    if claim_mode != "catch_up":
                        effective_ready_events = max(1, min(min_ready_events, max_events))
                        if effective_wait_seconds is not None:
                            effective_wait_seconds = min(
                                effective_wait_seconds,
                                DEFAULT_L2_STEADY_STATE_MAX_WAIT_SECONDS,
                            )

                    claim_count = 0
                    if pending_count >= effective_ready_events:
                        claim_count = min((pending_count // effective_ready_events) * effective_ready_events, remaining)
                        claim_count -= claim_count % effective_ready_events
                    elif effective_wait_seconds is not None and oldest_age_seconds >= effective_wait_seconds:
                        claim_count = min(pending_count, remaining)

                    if (
                        claim_count <= 0
                        and claim_mode == "catch_up"
                        and catch_up_owner
                        and pending_count < max_events
                    ):
                        low_frequency_owners_by_tail.setdefault(catch_up_owner, []).append(owner_row)
                        continue

                    if claim_count <= 0:
                        continue

                    async with db.execute(
                        """
                        SELECT event_id
                        FROM l2_projection_jobs
                        WHERE status = 'pending'
                          AND batch_owner = ?
                        ORDER BY created_at ASC
                        LIMIT ?
                        """,
                        (owner, claim_count),
                    ) as cursor:
                        event_rows = await cursor.fetchall()
                    owner_event_ids = [str(row["event_id"]) for row in event_rows]
                    selected_event_ids.extend(owner_event_ids)
                    effective_owner_by_event_id.update({event_id: owner for event_id in owner_event_ids})
                    remaining -= len(owner_event_ids)

                if claim_mode == "catch_up" and remaining > 0 and low_frequency_owners_by_tail:
                    tail_rows = sorted(
                        low_frequency_owners_by_tail.items(),
                        key=lambda item: min(float(row["oldest_created_at"] or now) for row in item[1]),
                    )
                    for catch_up_owner, grouped_rows in tail_rows:
                        if remaining <= 0:
                            break
                        owner_names = [str(row["batch_owner"] or "").strip() for row in grouped_rows]
                        owner_names = [owner for owner in owner_names if owner]
                        if not owner_names:
                            continue

                        pending_count = sum(int(row["pending_count"] or 0) for row in grouped_rows)
                        max_events = min(max(1, int(row["bucket_max_events"] or 1)) for row in grouped_rows)
                        oldest_created_at = min(float(row["oldest_created_at"] or now) for row in grouped_rows)
                        oldest_age_seconds = max(0.0, now - oldest_created_at)
                        max_wait_candidates = [
                            float(row["bucket_max_wait_seconds"])
                            for row in grouped_rows
                            if row["bucket_max_wait_seconds"] is not None
                        ]
                        effective_wait_seconds = min(max_wait_candidates) if max_wait_candidates else None

                        claim_count = 0
                        if pending_count >= max_events:
                            claim_count = min((pending_count // max_events) * max_events, remaining)
                            claim_count -= claim_count % max_events
                        elif effective_wait_seconds is not None and oldest_age_seconds >= effective_wait_seconds:
                            claim_count = min(pending_count, remaining)

                        if claim_count <= 0:
                            continue

                        placeholders = ", ".join("?" for _ in owner_names)
                        async with db.execute(
                            f"""
                            SELECT event_id
                            FROM l2_projection_jobs
                            WHERE status = 'pending'
                              AND batch_owner IN ({placeholders})
                            ORDER BY created_at ASC
                            LIMIT ?
                            """,
                            (*owner_names, claim_count),
                        ) as cursor:
                            event_rows = await cursor.fetchall()
                        tail_event_ids = [str(row["event_id"]) for row in event_rows]
                        if not tail_event_ids:
                            continue
                        selected_event_ids.extend(tail_event_ids)
                        effective_owner_by_event_id.update(
                            {event_id: catch_up_owner for event_id in tail_event_ids}
                        )
                        remaining -= len(tail_event_ids)

            if not selected_event_ids:
                return []

            placeholders = ", ".join("?" for _ in selected_event_ids)
            await db.execute(
                f"""
                UPDATE l2_projection_jobs
                SET status = 'queued',
                    claimed_by = ?,
                    claimed_at = ?,
                    started_at = NULL,
                    updated_at = ?
                WHERE event_id IN ({placeholders})
                """,
                (consumer_name, now, now, *selected_event_ids),
            )
            async with db.execute(
                f"""
                SELECT *
                FROM l2_projection_jobs
                WHERE event_id IN ({placeholders})
                """,
                tuple(selected_event_ids),
            ) as cursor:
                claimed_rows = await cursor.fetchall()
            await db.commit()

        order = {event_id: index for index, event_id in enumerate(selected_event_ids)}
        claimed_dicts = [self._row_to_dict(row) for row in claimed_rows]
        for item in claimed_dicts:
            event_id = str(item.get("event_id") or "")
            effective_owner = effective_owner_by_event_id.get(event_id)
            if effective_owner:
                item["effective_batch_owner"] = effective_owner
        claimed_dicts.sort(key=lambda item: order.get(str(item.get("event_id") or ""), requested_limit))
        return claimed_dicts

    async def claim(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim up to *limit* pending projection jobs ordered by creation time."""
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                UPDATE l2_projection_jobs
                SET status = 'queued',
                    claimed_by = ?,
                    claimed_at = ?,
                    started_at = NULL,
                    updated_at = ?
                WHERE event_id IN (
                    SELECT event_id
                    FROM l2_projection_jobs
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT ?
                )
                RETURNING *
                """,
                (
                    consumer_name,
                    now,
                    now,
                    int(limit),
                ),
            )
            rows = await cursor.fetchall()
            await db.commit()
        return [self._row_to_dict(row) for row in rows]

    async def mark_running(
        self,
        event_ids: List[str],
        *,
        consumer_name: str,
    ) -> int:
        """Mark queued projection jobs as actively running."""
        if not event_ids:
            return 0
        placeholders = ", ".join("?" for _ in event_ids)
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE l2_projection_jobs
                SET status = 'running',
                    claimed_by = ?,
                    started_at = ?,
                    updated_at = ?
                WHERE event_id IN ({placeholders})
                  AND status = 'queued'
                """,
                (
                    consumer_name,
                    now,
                    now,
                    *event_ids,
                ),
            )
            await db.commit()
        return int(cursor.rowcount or 0)

    async def complete(self, event_ids: List[str]) -> int:
        """Mark projection jobs as completed."""
        return await self._update_status(
            event_ids=event_ids,
            status="completed",
            clear_claim=True,
            completed_at=time.time(),
        )

    async def fail(
        self,
        event_ids: List[str],
        *,
        error_text: str | None = None,
        requeue: bool,
    ) -> int:
        """Mark projection jobs as failed or return them to pending."""
        next_status = "pending" if requeue else "failed"
        return await self._update_status(
            event_ids=event_ids,
            status=next_status,
            clear_claim=True,
            completed_at=None,
            error_text=error_text,
            increment_attempt_count=True,
        )

    async def requeue_stale(
        self,
        *,
        queued_timeout_seconds: float,
        running_timeout_seconds: float,
    ) -> int:
        """Return stale queued or running jobs back to pending for replay."""
        now = time.time()
        queued_cutoff = now - float(queued_timeout_seconds)
        running_cutoff = now - float(running_timeout_seconds)
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE l2_projection_jobs
                SET status = 'pending',
                    attempt_count = attempt_count + 1,
                    claimed_by = NULL,
                    claimed_at = NULL,
                    started_at = NULL,
                    updated_at = ?
                WHERE (
                    status = 'queued'
                    AND claimed_at IS NOT NULL
                    AND claimed_at < ?
                ) OR (
                    status = 'running'
                    AND started_at IS NOT NULL
                    AND started_at < ?
                )
                """,
                (now, queued_cutoff, running_cutoff),
            )
            await db.commit()
        return int(cursor.rowcount or 0)

    async def get_backlog_stats(self) -> Dict[str, int]:
        """Return counts for durable projection jobs by status."""
        async with sqlite_connection_async(self.db_path) as db:
            pending = await self._count_by_status(db, "pending")
            queued = await self._count_by_status(db, "queued")
            running = await self._count_by_status(db, "running")
            completed = await self._count_by_status(db, "completed")
            failed = await self._count_by_status(db, "failed")
        return {
            "pending": pending,
            "queued": queued,
            "running": running,
            "claimed": queued + running,
            "completed": completed,
            "failed": failed,
        }

    async def clear_all(self) -> None:
        """Delete all projection jobs."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("DELETE FROM l2_projection_jobs")
            await db.commit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _update_status(
        self,
        *,
        event_ids: List[str],
        status: str,
        clear_claim: bool,
        completed_at: float | None,
        error_text: str | None = None,
        increment_attempt_count: bool = False,
    ) -> int:
        if not event_ids:
            return 0
        placeholders = ", ".join("?" for _ in event_ids)
        now = time.time()
        attempt_clause = "attempt_count = attempt_count + 1," if increment_attempt_count else ""
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE l2_projection_jobs
                SET status = ?,
                    {attempt_clause}
                    claimed_by = ?,
                    claimed_at = ?,
                    started_at = ?,
                    completed_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE event_id IN ({placeholders})
                """,
                (
                    status,
                    None if clear_claim else "runtime_worker",
                    None if clear_claim else now,
                    None if clear_claim else now,
                    completed_at,
                    error_text,
                    now,
                    *event_ids,
                ),
            )
            await db.commit()
        return int(cursor.rowcount or 0)

    @staticmethod
    async def _count_by_status(db: aiosqlite.Connection, status: str) -> int:
        async with db.execute(
            "SELECT COUNT(*) FROM l2_projection_jobs WHERE status = ?",
            (status,),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "source": str(row["source"]),
            "event_type": str(row["event_type"]),
            "batch_owner": row["batch_owner"],
            "catch_up_owner": row["catch_up_owner"],
            "max_events": int(row["max_events"]) if row["max_events"] is not None else None,
            "min_ready_events": int(row["min_ready_events"]) if row["min_ready_events"] is not None else None,
            "max_wait_seconds": float(row["max_wait_seconds"]) if row["max_wait_seconds"] is not None else None,
            "status": str(row["status"]),
            "attempt_count": int(row["attempt_count"] or 0),
            "claimed_by": row["claimed_by"],
            "claimed_at": float(row["claimed_at"]) if row["claimed_at"] is not None else None,
            "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
            "completed_at": float(row["completed_at"]) if row["completed_at"] is not None else None,
            "last_error": row["last_error"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }
