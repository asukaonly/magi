"""Durable projection job queue for L2 cognition pipeline.

Manages the lifecycle of event projection jobs:
pending → queued → running → completed/failed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from .claiming import ProjectionQueueClaimingMixin

DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD = 300
DEFAULT_L2_STEADY_STATE_MAX_WAIT_SECONDS = 45.0

logger = get_logger(__name__)


class ProjectionJobQueue(ProjectionQueueClaimingMixin):
    """Persistent queue for L2 extraction projection jobs.

    Shares the same SQLite database as ``L2CognitionStore`` but owns
    all logic for the ``l2_projection_jobs`` table exclusively.
    """

    def __init__(self, *, db_path: str) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def has_job(self, *, event_id: str) -> bool:
        """Return whether a durable projection job exists for an L1 event."""
        normalized_event_id = str(event_id or "").strip()
        if not normalized_event_id:
            return False
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM l2_projection_jobs WHERE event_id = ? LIMIT 1",
                (normalized_event_id,),
            )
            return await cursor.fetchone() is not None

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

    async def get_backlog_stats(self, *, source_filter: str | None = None) -> Dict[str, int]:
        """Return counts for durable projection jobs by status."""
        async with sqlite_connection_async(self.db_path) as db:
            pending = await self._count_by_status(db, "pending", source_filter=source_filter)
            queued = await self._count_by_status(db, "queued", source_filter=source_filter)
            running = await self._count_by_status(db, "running", source_filter=source_filter)
            completed = await self._count_by_status(db, "completed", source_filter=source_filter)
            failed = await self._count_by_status(db, "failed", source_filter=source_filter)
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
    async def _count_by_status(
        db: aiosqlite.Connection,
        status: str,
        *,
        source_filter: str | None = None,
    ) -> int:
        query = "SELECT COUNT(*) FROM l2_projection_jobs WHERE status = ?"
        params: tuple[str, ...] = (status,)
        if source_filter:
            query = f"{query} AND source = ?"
            params = (status, source_filter)
        async with db.execute(query, params) as cursor:
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
            "min_ready_events": int(row["min_ready_events"])
            if row["min_ready_events"] is not None
            else None,
            "max_wait_seconds": float(row["max_wait_seconds"])
            if row["max_wait_seconds"] is not None
            else None,
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
