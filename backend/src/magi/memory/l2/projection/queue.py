"""Durable projection job queue for L2 cognition pipeline.

Manages the lifecycle of event projection jobs:
pending → queued → running → completed/failed.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any, Dict, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from .claiming import ProjectionQueueClaimingMixin
from ..batch_models import L2ProjectionLease
from .governance import active_projection_event_predicate, ready_projection_job_predicate

DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD = 300
DEFAULT_L2_STEADY_STATE_MAX_WAIT_SECONDS = 45.0
DEFAULT_L2_PROJECTION_MAX_ATTEMPTS = 5

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
        normalized_event_id = str(event_id or "").strip()
        if not normalized_event_id:
            return False
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"""
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
                    lease_token,
                    lease_heartbeat_at,
                    next_retry_at,
                    max_attempts,
                    terminal_at,
                    claimed_by,
                    claimed_at,
                    started_at,
                    completed_at,
                    last_error,
                    created_at,
                    updated_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?,
                       'pending', 0, NULL, NULL, NULL, ?, NULL,
                       NULL, NULL, NULL, NULL, NULL, ?, ?
                WHERE {active_projection_event_predicate('?')}
                """,
                (
                    normalized_event_id,
                    source,
                    event_type,
                    batch_owner,
                    catch_up_owner,
                    max_events,
                    min_ready_events,
                    max_wait_seconds,
                    DEFAULT_L2_PROJECTION_MAX_ATTEMPTS,
                    now,
                    now,
                    normalized_event_id,
                    normalized_event_id,
                ),
            )
            await db.commit()
        return bool(cursor.rowcount)

    async def request_replay(self, *, event_id: str) -> bool:
        """Durably request a fresh attempt for an existing active source event."""

        normalized_event_id = str(event_id or "").strip()
        if not normalized_event_id:
            return False
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    f"""
                    SELECT status, replay_requested
                    FROM l2_projection_jobs AS jobs
                    WHERE jobs.event_id = ?
                      AND {active_projection_event_predicate('jobs.event_id')}
                    """,
                    (normalized_event_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    await db.rollback()
                    return False
                status = str(row["status"])
                if status in {"pending", "completed", "failed"}:
                    cursor = await db.execute(
                        """
                        UPDATE l2_projection_jobs
                        SET status = 'pending', attempt_count = 0,
                            lease_token = NULL, lease_heartbeat_at = NULL,
                            next_retry_at = NULL, terminal_at = NULL,
                            replay_requested = 0,
                            claimed_by = NULL, claimed_at = NULL,
                            started_at = NULL, completed_at = NULL,
                            last_error = NULL, updated_at = ?
                        WHERE event_id = ? AND status IN ('pending', 'completed', 'failed')
                        """,
                        (now, normalized_event_id),
                    )
                    accepted = bool(cursor.rowcount)
                elif status in {"queued", "running"}:
                    cursor = await db.execute(
                        """
                        UPDATE l2_projection_jobs
                        SET replay_requested = 1, updated_at = ?
                        WHERE event_id = ? AND status IN ('queued', 'running')
                        """,
                        (now, normalized_event_id),
                    )
                    accepted = bool(cursor.rowcount)
                else:
                    accepted = False
                await db.commit()
                return accepted
            except Exception:
                await db.rollback()
                raise

    async def recover_foreign_attempts(self, *, consumer_name: str) -> int:
        """Recover leases owned by a previous backend process immediately."""

        normalized_consumer = str(consumer_name or "").strip()
        if not normalized_consumer:
            return 0
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE l2_projection_jobs
                SET status = CASE
                        WHEN replay_requested = 0 AND attempt_count >= max_attempts
                            THEN 'failed'
                        ELSE 'pending'
                    END,
                    attempt_count = CASE
                        WHEN replay_requested = 1 THEN 0
                        ELSE attempt_count
                    END,
                    lease_token = NULL,
                    lease_heartbeat_at = NULL,
                    next_retry_at = NULL,
                    terminal_at = CASE
                        WHEN replay_requested = 0 AND attempt_count >= max_attempts THEN ?
                        ELSE NULL
                    END,
                    replay_requested = 0,
                    claimed_by = NULL,
                    claimed_at = NULL,
                    started_at = NULL,
                    completed_at = NULL,
                    last_error = CASE
                        WHEN replay_requested = 1
                            THEN 'projection_replay_recovered_on_startup'
                        WHEN attempt_count >= max_attempts
                            THEN 'projection_attempt_budget_exhausted_on_startup'
                        ELSE 'projection_attempt_recovered_on_startup'
                    END,
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                  AND (claimed_by IS NULL OR claimed_by != ?)
                  AND {active_projection_event_predicate('l2_projection_jobs.event_id')}
                """,
                (now, now, normalized_consumer),
            )
            await db.commit()
        return max(int(cursor.rowcount or 0), 0)

    async def claim_ready(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim ready jobs while rejecting non-positive limits."""

        if int(limit) <= 0:
            return []
        return cast(
            list[Dict[str, Any]],
            await super().claim_ready(
                consumer_name=consumer_name,
                limit=limit,
            ),
        )

    async def claim(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim up to *limit* pending projection jobs ordered by creation time."""
        if int(limit) <= 0:
            return []
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                UPDATE l2_projection_jobs
                SET status = 'queued',
                    attempt_count = attempt_count + 1,
                    lease_token = lower(hex(randomblob(16))),
                    lease_heartbeat_at = NULL,
                    next_retry_at = NULL,
                    terminal_at = NULL,
                    claimed_by = ?,
                    claimed_at = ?,
                    started_at = NULL,
                    updated_at = ?
                WHERE event_id IN (
                    SELECT event_id
                    FROM l2_projection_jobs AS jobs
                    WHERE {ready_projection_job_predicate('jobs')}
                      AND {active_projection_event_predicate('jobs.event_id')}
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
        leases: Iterable[L2ProjectionLease],
        *,
        consumer_name: str,
    ) -> int:
        """Mark a complete claimed batch running, or requeue its active rows."""
        normalized_leases = _normalized_leases(leases)
        if not normalized_leases:
            return 0
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for lease in normalized_leases:
                    async with db.execute(
                        f"""
                        SELECT 1 FROM l2_projection_jobs AS jobs
                        WHERE jobs.event_id = ? AND jobs.status = 'queued'
                          AND jobs.claimed_by = ? AND jobs.lease_token = ?
                          AND jobs.attempt_count = ?
                          AND {active_projection_event_predicate('jobs.event_id')}
                        """,
                        (
                            lease.event_id,
                            consumer_name,
                            lease.lease_token,
                            lease.attempt_count,
                        ),
                    ) as cursor:
                        if await cursor.fetchone() is None:
                            await self._release_queued_attempts(
                                db,
                                leases=normalized_leases,
                                consumer_name=consumer_name,
                                now=now,
                            )
                            await db.commit()
                            return 0

                transitioned = 0
                for lease in normalized_leases:
                    cursor = await db.execute(
                        f"""
                        UPDATE l2_projection_jobs
                        SET status = 'running', started_at = ?,
                            lease_heartbeat_at = ?, updated_at = ?
                        WHERE event_id = ? AND status = 'queued'
                          AND claimed_by = ? AND lease_token = ?
                          AND attempt_count = ?
                          AND {active_projection_event_predicate('l2_projection_jobs.event_id')}
                        """,
                        (
                            now,
                            now,
                            now,
                            lease.event_id,
                            consumer_name,
                            lease.lease_token,
                            lease.attempt_count,
                        ),
                    )
                    transitioned += max(int(cursor.rowcount or 0), 0)
                if transitioned != len(normalized_leases):
                    await db.rollback()
                    return 0
                await db.commit()
                return transitioned
            except BaseException:
                await db.rollback()
                raise

    async def complete(self, leases: Iterable[L2ProjectionLease]) -> int:
        """Complete only the running attempts that still own their leases."""

        return await self._finish_attempts(leases, completed=True)

    async def touch_running(self, leases: Iterable[L2ProjectionLease]) -> int:
        """Refresh a complete running lease set, or fence the whole batch out."""

        normalized_leases = _normalized_leases(leases)
        if not normalized_leases:
            return 0
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for lease in normalized_leases:
                    async with db.execute(
                        f"""
                        SELECT 1 FROM l2_projection_jobs AS jobs
                        WHERE jobs.event_id = ? AND jobs.status = 'running'
                          AND jobs.lease_token = ? AND jobs.attempt_count = ?
                          AND {active_projection_event_predicate('jobs.event_id')}
                        """,
                        (lease.event_id, lease.lease_token, lease.attempt_count),
                    ) as cursor:
                        if await cursor.fetchone() is None:
                            await db.rollback()
                            return 0
                transitioned = 0
                for lease in normalized_leases:
                    cursor = await db.execute(
                        """
                        UPDATE l2_projection_jobs
                        SET lease_heartbeat_at = ?, updated_at = ?
                        WHERE event_id = ? AND status = 'running'
                          AND lease_token = ? AND attempt_count = ?
                        """,
                        (
                            now,
                            now,
                            lease.event_id,
                            lease.lease_token,
                            lease.attempt_count,
                        ),
                    )
                    transitioned += max(int(cursor.rowcount or 0), 0)
                if transitioned != len(normalized_leases):
                    await db.rollback()
                    return 0
                await db.commit()
                return transitioned
            except BaseException:
                await db.rollback()
                raise

    async def fail(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        error_text: str | None = None,
        requeue: bool,
    ) -> int:
        """Fail only attempts that still own their queued/running leases."""

        return await self._finish_attempts(
            leases,
            completed=False,
            error_text=error_text,
            requeue=requeue,
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
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    f"""
                    SELECT event_id, attempt_count, max_attempts, replay_requested
                    FROM l2_projection_jobs
                    WHERE (
                        (status = 'queued' AND claimed_at IS NOT NULL AND claimed_at < ?)
                        OR
                        (
                            status = 'running'
                            AND COALESCE(lease_heartbeat_at, started_at) IS NOT NULL
                            AND COALESCE(lease_heartbeat_at, started_at) < ?
                        )
                    )
                    AND {active_projection_event_predicate('l2_projection_jobs.event_id')}
                    """,
                    (queued_cutoff, running_cutoff),
                ) as cursor:
                    stale_rows = await cursor.fetchall()
                transitioned = 0
                for row in stale_rows:
                    attempt_count = int(row["attempt_count"] or 0)
                    replay_requested = bool(row["replay_requested"])
                    terminal = not replay_requested and attempt_count >= int(
                        row["max_attempts"] or 1
                    )
                    cursor = await db.execute(
                        """
                        UPDATE l2_projection_jobs
                        SET status = ?, attempt_count = ?,
                            lease_token = NULL, lease_heartbeat_at = NULL,
                            claimed_by = NULL,
                            claimed_at = NULL, started_at = NULL,
                            next_retry_at = ?, terminal_at = ?, replay_requested = 0,
                            last_error = ?, updated_at = ?
                        WHERE event_id = ? AND status IN ('queued', 'running')
                          AND attempt_count = ?
                        """,
                        (
                            "failed" if terminal else "pending",
                            0 if replay_requested else attempt_count,
                            (
                                None
                                if terminal or replay_requested
                                else now + _retry_delay_seconds(attempt_count)
                            ),
                            now if terminal else None,
                            None if replay_requested else "projection_attempt_stale",
                            now,
                            str(row["event_id"]),
                            attempt_count,
                        ),
                    )
                    transitioned += max(int(cursor.rowcount or 0), 0)
                await db.commit()
                return transitioned
            except BaseException:
                await db.rollback()
                raise

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

    async def _finish_attempts(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        completed: bool,
        error_text: str | None = None,
        requeue: bool = False,
    ) -> int:
        normalized_leases = _normalized_leases(leases)
        if not normalized_leases:
            return 0
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                allowed_statuses = ("running",) if completed else ("queued", "running")
                status_placeholders = ", ".join("?" for _ in allowed_statuses)
                attempt_state_by_event: dict[str, tuple[int, bool]] = {}
                for lease in normalized_leases:
                    async with db.execute(
                        f"""
                        SELECT max_attempts, replay_requested
                        FROM l2_projection_jobs
                        WHERE event_id = ? AND lease_token = ?
                          AND attempt_count = ? AND status IN ({status_placeholders})
                        """,
                        (
                            lease.event_id,
                            lease.lease_token,
                            lease.attempt_count,
                            *allowed_statuses,
                        ),
                    ) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        await db.rollback()
                        return 0
                    attempt_state_by_event[lease.event_id] = (
                        int(row["max_attempts"] or 1),
                        bool(row["replay_requested"]),
                    )
                transitioned = 0
                for lease in normalized_leases:
                    max_attempts, replay_requested = attempt_state_by_event[lease.event_id]
                    terminal = not completed and (
                        not requeue or lease.attempt_count >= max_attempts
                    )
                    if replay_requested:
                        status = "pending"
                        next_attempt_count = 0
                        next_retry_at = None
                        terminal_at = None
                        completed_at = None
                        next_error = None
                    elif completed:
                        status = "completed"
                        next_attempt_count = lease.attempt_count
                        next_retry_at = None
                        terminal_at = None
                        completed_at = now
                        next_error = None
                    elif terminal:
                        status = "failed"
                        next_attempt_count = lease.attempt_count
                        next_retry_at = None
                        terminal_at = now
                        completed_at = None
                        next_error = error_text
                    else:
                        status = "pending"
                        next_attempt_count = lease.attempt_count
                        next_retry_at = now + _retry_delay_seconds(lease.attempt_count)
                        terminal_at = None
                        completed_at = None
                        next_error = error_text
                    cursor = await db.execute(
                        f"""
                        UPDATE l2_projection_jobs
                        SET status = ?, attempt_count = ?,
                            lease_token = NULL, lease_heartbeat_at = NULL,
                            claimed_by = NULL,
                            claimed_at = NULL, started_at = NULL, completed_at = ?,
                            next_retry_at = ?, terminal_at = ?, replay_requested = 0,
                            last_error = ?, updated_at = ?
                        WHERE event_id = ? AND lease_token = ? AND attempt_count = ?
                          AND status IN ({status_placeholders})
                        """,
                        (
                            status,
                            next_attempt_count,
                            completed_at,
                            next_retry_at,
                            terminal_at,
                            next_error,
                            now,
                            lease.event_id,
                            lease.lease_token,
                            lease.attempt_count,
                            *allowed_statuses,
                        ),
                    )
                    transitioned += max(int(cursor.rowcount or 0), 0)
                await db.commit()
                return transitioned
            except BaseException:
                await db.rollback()
                raise

    @staticmethod
    async def _count_by_status(
        db: aiosqlite.Connection,
        status: str,
        *,
        source_filter: str | None = None,
    ) -> int:
        query = "SELECT COUNT(*) FROM l2_projection_jobs AS jobs WHERE jobs.status = ?"
        params: tuple[str, ...] = (status,)
        if status in {"pending", "queued", "running"}:
            query += f" AND {active_projection_event_predicate('jobs.event_id')}"
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
            "min_ready_events": (
                int(row["min_ready_events"]) if row["min_ready_events"] is not None else None
            ),
            "max_wait_seconds": (
                float(row["max_wait_seconds"]) if row["max_wait_seconds"] is not None else None
            ),
            "status": str(row["status"]),
            "attempt_count": int(row["attempt_count"] or 0),
            "lease_token": row["lease_token"],
            "lease_heartbeat_at": (
                float(row["lease_heartbeat_at"]) if row["lease_heartbeat_at"] is not None else None
            ),
            "next_retry_at": (
                float(row["next_retry_at"]) if row["next_retry_at"] is not None else None
            ),
            "max_attempts": int(row["max_attempts"] or DEFAULT_L2_PROJECTION_MAX_ATTEMPTS),
            "terminal_at": (float(row["terminal_at"]) if row["terminal_at"] is not None else None),
            "replay_requested": bool(row["replay_requested"]),
            "claimed_by": row["claimed_by"],
            "claimed_at": float(row["claimed_at"]) if row["claimed_at"] is not None else None,
            "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
            "completed_at": float(row["completed_at"]) if row["completed_at"] is not None else None,
            "last_error": row["last_error"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    @staticmethod
    async def _release_queued_attempts(
        db: aiosqlite.Connection,
        *,
        leases: list[L2ProjectionLease],
        consumer_name: str,
        now: float,
    ) -> int:
        """Release still-owned queued rows when a batch cannot start atomically."""

        released = 0
        for lease in leases:
            cursor = await db.execute(
                """
                UPDATE l2_projection_jobs
                SET status = CASE
                        WHEN replay_requested = 0 AND attempt_count >= max_attempts
                            THEN 'failed'
                        ELSE 'pending'
                    END,
                    attempt_count = CASE
                        WHEN replay_requested = 1 THEN 0
                        ELSE attempt_count
                    END,
                    lease_token = NULL,
                    lease_heartbeat_at = NULL, claimed_by = NULL,
                    claimed_at = NULL, started_at = NULL,
                    next_retry_at = NULL,
                    terminal_at = CASE
                        WHEN replay_requested = 0 AND attempt_count >= max_attempts THEN ?
                        ELSE NULL
                    END,
                    replay_requested = 0,
                    last_error = CASE
                        WHEN replay_requested = 1 THEN NULL
                        WHEN attempt_count >= max_attempts
                            THEN 'projection_attempt_budget_exhausted_before_start'
                        ELSE last_error
                    END,
                    updated_at = ?
                WHERE event_id = ? AND status = 'queued'
                  AND claimed_by = ? AND lease_token = ? AND attempt_count = ?
                """,
                (
                    now,
                    now,
                    lease.event_id,
                    consumer_name,
                    lease.lease_token,
                    lease.attempt_count,
                ),
            )
            released += max(int(cursor.rowcount or 0), 0)
        return released


def _normalized_leases(leases: Iterable[L2ProjectionLease]) -> list[L2ProjectionLease]:
    normalized: list[L2ProjectionLease] = []
    seen: set[str] = set()
    for lease in leases:
        if not isinstance(lease, L2ProjectionLease):
            raise TypeError("projection lease must be an L2ProjectionLease")
        if lease.event_id in seen:
            raise ValueError("projection leases must contain unique event IDs")
        seen.add(lease.event_id)
        normalized.append(lease)
    return normalized


def _retry_delay_seconds(attempt_count: int) -> float:
    return min(300.0, 2.0 ** max(0, int(attempt_count) - 1))
