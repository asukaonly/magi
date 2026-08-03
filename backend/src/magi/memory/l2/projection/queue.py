"""Durable projection job queue for L2 cognition pipeline.

Manages the lifecycle of event projection jobs:
pending → queued → running → completed/failed.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Dict, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from .claiming import ProjectionQueueClaimingMixin
from ..batch_models import (
    L2ProjectionLease,
    derive_projection_attempt_key,
    projection_attempt_descriptor_json,
)
from .errors import ProjectionAttemptFencedError
from .fencing import assert_bound_projection_attempt
from .governance import active_projection_event_predicate, ready_projection_job_predicate

DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD = 300
DEFAULT_L2_STEADY_STATE_MAX_WAIT_SECONDS = 45.0
DEFAULT_L2_PROJECTION_MAX_ATTEMPTS = 5

logger = get_logger(__name__)

ProjectionTerminalCallback = Callable[
    [aiosqlite.Connection, tuple[L2ProjectionLease, ...]],
    Awaitable[None],
]
ProjectionCompletionCallback = Callable[
    [aiosqlite.Connection, tuple[L2ProjectionLease, ...]],
    Awaitable[None],
]


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
                            batch_attempt_key = NULL,
                            batch_descriptor_json = NULL, batch_bound_at = NULL,
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

    async def recover_foreign_attempts(
        self,
        *,
        consumer_name: str,
        terminal_callback: ProjectionTerminalCallback | None = None,
    ) -> int:
        """Recover leases owned by a previous backend process immediately."""

        normalized_consumer = str(consumer_name or "").strip()
        if not normalized_consumer:
            return 0
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    f"""
                    SELECT event_id, lease_token, attempt_count,
                           max_attempts, replay_requested,
                           batch_attempt_key, batch_descriptor_json
                    FROM l2_projection_jobs
                    WHERE status IN ('queued', 'running')
                      AND (claimed_by IS NULL OR claimed_by != ?)
                      AND {active_projection_event_predicate('l2_projection_jobs.event_id')}
                    """,
                    (normalized_consumer,),
                ) as rows_cursor:
                    candidate_rows = list(await rows_cursor.fetchall())
                groups = await _recovery_groups(db, candidate_rows)
                transitioned = 0
                for rows, descriptor_valid in groups:
                    leases = tuple(_lease_from_active_row(row) for row in rows)
                    batch_replay = any(bool(row["replay_requested"]) for row in rows)
                    terminal = (
                        descriptor_valid
                        and not batch_replay
                        and any(
                            int(row["attempt_count"] or 0) >= int(row["max_attempts"] or 1)
                            for row in rows
                        )
                    )
                    if terminal and terminal_callback is not None:
                        await terminal_callback(db, leases)
                    for row in rows:
                        attempt_count = int(row["attempt_count"] or 0)
                        if not descriptor_valid:
                            next_status = "pending"
                            next_attempt_count = 0 if batch_replay else max(0, attempt_count - 1)
                            last_error = (
                                None
                                if batch_replay
                                else "projection_attempt_descriptor_invalid_on_startup"
                            )
                        elif terminal:
                            next_status = "failed"
                            next_attempt_count = attempt_count
                            last_error = "projection_attempt_budget_exhausted_on_startup"
                        else:
                            next_status = "pending"
                            next_attempt_count = 0 if batch_replay else attempt_count
                            last_error = (
                                "projection_replay_recovered_on_startup"
                                if batch_replay
                                else "projection_attempt_recovered_on_startup"
                            )
                        cursor = await db.execute(
                            """
                            UPDATE l2_projection_jobs
                            SET status = ?, attempt_count = ?,
                                lease_token = NULL, lease_heartbeat_at = NULL,
                                batch_attempt_key = NULL,
                                batch_descriptor_json = NULL, batch_bound_at = NULL,
                                next_retry_at = NULL, terminal_at = ?,
                                replay_requested = 0,
                                claimed_by = NULL, claimed_at = NULL,
                                started_at = NULL, completed_at = NULL,
                                last_error = ?, updated_at = ?
                            WHERE event_id = ? AND status IN ('queued', 'running')
                              AND lease_token = ? AND attempt_count = ?
                            """,
                            (
                                next_status,
                                next_attempt_count,
                                now if terminal else None,
                                last_error,
                                now,
                                str(row["event_id"]),
                                str(row["lease_token"]),
                                attempt_count,
                            ),
                        )
                        transitioned += max(int(cursor.rowcount or 0), 0)
                await db.commit()
                return transitioned
            except BaseException:
                await db.rollback()
                raise

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
                    batch_attempt_key = NULL,
                    batch_descriptor_json = NULL,
                    batch_bound_at = NULL,
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

    async def bind_queued_batch(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        consumer_name: str,
        attempt_key: str | None = None,
    ) -> int:
        """Persist the queue-issued exact descriptor for one final batch."""

        normalized_leases = _normalized_leases(leases)
        normalized_consumer = str(consumer_name or "").strip()
        if not normalized_leases or not normalized_consumer:
            return 0
        derived_attempt_key = derive_projection_attempt_key(normalized_leases)
        supplied_attempt_key = str(attempt_key or "").strip()
        if supplied_attempt_key and supplied_attempt_key != derived_attempt_key:
            return 0
        attempt_key = derived_attempt_key
        descriptor_json = projection_attempt_descriptor_json(normalized_leases)
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for lease in normalized_leases:
                    cursor = await db.execute(
                        f"""
                        UPDATE l2_projection_jobs
                        SET batch_attempt_key = ?, batch_descriptor_json = ?,
                            batch_bound_at = COALESCE(batch_bound_at, ?), updated_at = ?
                        WHERE event_id = ? AND status = 'queued'
                          AND claimed_by = ? AND lease_token = ?
                          AND attempt_count = ?
                          AND (batch_attempt_key IS NULL OR batch_attempt_key = ?)
                          AND (
                              batch_descriptor_json IS NULL
                              OR batch_descriptor_json = ?
                          )
                          AND {active_projection_event_predicate('l2_projection_jobs.event_id')}
                        """,
                        (
                            attempt_key,
                            descriptor_json,
                            now,
                            now,
                            lease.event_id,
                            normalized_consumer,
                            lease.lease_token,
                            lease.attempt_count,
                            attempt_key,
                            descriptor_json,
                        ),
                    )
                    if int(cursor.rowcount or 0) != 1:
                        released = await _release_failed_batch_binding(
                            db,
                            leases=normalized_leases,
                            consumer_name=normalized_consumer,
                            attempt_key=attempt_key,
                            descriptor_json=descriptor_json,
                            now=now,
                        )
                        if released < 0:
                            await db.rollback()
                        else:
                            await db.commit()
                        return 0
                try:
                    await assert_bound_projection_attempt(
                        db,
                        normalized_leases,
                        allowed_statuses=("queued",),
                        claimed_by=normalized_consumer,
                    )
                except ProjectionAttemptFencedError:
                    released = await _release_failed_batch_binding(
                        db,
                        leases=normalized_leases,
                        consumer_name=normalized_consumer,
                        attempt_key=attempt_key,
                        descriptor_json=descriptor_json,
                        now=now,
                    )
                    if released < 0:
                        await db.rollback()
                    else:
                        await db.commit()
                    return 0
                await db.commit()
                return len(normalized_leases)
            except BaseException:
                await db.rollback()
                raise

    async def mark_running(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        consumer_name: str,
    ) -> int:
        """Mark only an exactly bound queued batch as running."""
        normalized_leases = _normalized_leases(leases)
        if not normalized_leases:
            return 0
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                try:
                    await assert_bound_projection_attempt(
                        db,
                        normalized_leases,
                        allowed_statuses=("queued",),
                        claimed_by=consumer_name,
                    )
                except ProjectionAttemptFencedError:
                    await db.rollback()
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

    async def complete(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        completion_callback: ProjectionCompletionCallback | None = None,
    ) -> int:
        """Complete only the running attempts that still own their leases."""

        return await self._finish_attempts(
            leases,
            completed=True,
            completion_callback=completion_callback,
        )

    async def touch_running(self, leases: Iterable[L2ProjectionLease]) -> int:
        """Refresh a complete running lease set, or fence the whole batch out."""

        normalized_leases = _normalized_leases(leases)
        if not normalized_leases:
            return 0
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                try:
                    await assert_bound_projection_attempt(
                        db,
                        normalized_leases,
                        allowed_statuses=("running",),
                    )
                except ProjectionAttemptFencedError:
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
        terminal_callback: ProjectionTerminalCallback | None = None,
    ) -> int:
        """Fail only attempts that still own their queued/running leases."""

        return await self._finish_attempts(
            leases,
            completed=False,
            error_text=error_text,
            requeue=requeue,
            terminal_callback=terminal_callback,
        )

    async def requeue_stale(
        self,
        *,
        queued_timeout_seconds: float,
        running_timeout_seconds: float,
        terminal_callback: ProjectionTerminalCallback | None = None,
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
                    SELECT event_id, lease_token, attempt_count,
                           max_attempts, replay_requested,
                           batch_attempt_key, batch_descriptor_json
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
                    candidate_rows = list(await cursor.fetchall())
                groups = await _recovery_groups(db, candidate_rows)
                transitioned = 0
                for rows, descriptor_valid in groups:
                    leases = tuple(_lease_from_active_row(row) for row in rows)
                    batch_replay = any(bool(row["replay_requested"]) for row in rows)
                    terminal = (
                        descriptor_valid
                        and not batch_replay
                        and any(
                            int(row["attempt_count"] or 0) >= int(row["max_attempts"] or 1)
                            for row in rows
                        )
                    )
                    if terminal and terminal_callback is not None:
                        await terminal_callback(db, leases)
                    for row in rows:
                        attempt_count = int(row["attempt_count"] or 0)
                        if not descriptor_valid:
                            next_status = "pending"
                            next_attempt_count = 0 if batch_replay else max(0, attempt_count - 1)
                            next_retry_at = None
                            last_error = (
                                None
                                if batch_replay
                                else "projection_attempt_descriptor_invalid_when_stale"
                            )
                        elif terminal:
                            next_status = "failed"
                            next_attempt_count = attempt_count
                            next_retry_at = None
                            last_error = "projection_attempt_stale"
                        elif batch_replay:
                            next_status = "pending"
                            next_attempt_count = 0
                            next_retry_at = None
                            last_error = None
                        else:
                            next_status = "pending"
                            next_attempt_count = attempt_count
                            next_retry_at = now + _retry_delay_seconds(attempt_count)
                            last_error = "projection_attempt_stale"
                        cursor = await db.execute(
                            """
                            UPDATE l2_projection_jobs
                            SET status = ?, attempt_count = ?,
                                lease_token = NULL, lease_heartbeat_at = NULL,
                                batch_attempt_key = NULL,
                                batch_descriptor_json = NULL, batch_bound_at = NULL,
                                claimed_by = NULL,
                                claimed_at = NULL, started_at = NULL,
                                completed_at = NULL,
                                next_retry_at = ?, terminal_at = ?, replay_requested = 0,
                                last_error = ?, updated_at = ?
                            WHERE event_id = ? AND status IN ('queued', 'running')
                              AND lease_token = ? AND attempt_count = ?
                            """,
                            (
                                next_status,
                                next_attempt_count,
                                next_retry_at,
                                now if terminal else None,
                                last_error,
                                now,
                                str(row["event_id"]),
                                str(row["lease_token"]),
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
        terminal_callback: ProjectionTerminalCallback | None = None,
        completion_callback: ProjectionCompletionCallback | None = None,
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
                try:
                    await assert_bound_projection_attempt(
                        db,
                        normalized_leases,
                        allowed_statuses=allowed_statuses,
                    )
                except ProjectionAttemptFencedError:
                    await db.rollback()
                    return 0
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
                batch_replay_requested = any(state[1] for state in attempt_state_by_event.values())
                terminal = (
                    not completed
                    and not batch_replay_requested
                    and (
                        not requeue
                        or any(
                            lease.attempt_count >= attempt_state_by_event[lease.event_id][0]
                            for lease in normalized_leases
                        )
                    )
                )
                terminal_leases = tuple(normalized_leases) if terminal else ()
                if terminal_callback is not None and terminal_leases:
                    await terminal_callback(db, terminal_leases)
                if completed and completion_callback is not None:
                    await completion_callback(db, tuple(normalized_leases))
                transitioned = 0
                for lease in normalized_leases:
                    _, event_replay_requested = attempt_state_by_event[lease.event_id]
                    if completed and event_replay_requested:
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
                    elif batch_replay_requested:
                        status = "pending"
                        next_attempt_count = 0
                        next_retry_at = None
                        terminal_at = None
                        completed_at = None
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
                            batch_attempt_key = NULL,
                            batch_descriptor_json = NULL, batch_bound_at = NULL,
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
            "batch_attempt_key": row["batch_attempt_key"],
            "batch_descriptor_json": row["batch_descriptor_json"],
            "batch_bound_at": (
                float(row["batch_bound_at"]) if row["batch_bound_at"] is not None else None
            ),
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


def _lease_from_active_row(row: aiosqlite.Row) -> L2ProjectionLease:
    lease_token = str(row["lease_token"] or "").strip()
    if not lease_token:
        raise RuntimeError("active projection job is missing its lease token")
    return L2ProjectionLease(
        event_id=str(row["event_id"]),
        lease_token=lease_token,
        attempt_count=int(row["attempt_count"] or 0),
    )


async def _recovery_groups(
    db: aiosqlite.Connection,
    candidate_rows: list[aiosqlite.Row],
) -> list[tuple[list[aiosqlite.Row], bool]]:
    """Expand recovery candidates to complete bound batches and validate them."""

    if not candidate_rows:
        return []
    rows_by_event = {str(row["event_id"]): row for row in candidate_rows}
    attempt_keys = sorted(
        {
            str(row["batch_attempt_key"] or "").strip()
            for row in candidate_rows
            if str(row["batch_attempt_key"] or "").strip()
        }
    )
    if attempt_keys:
        placeholders = ", ".join("?" for _ in attempt_keys)
        async with db.execute(
            f"""
            SELECT event_id, lease_token, attempt_count,
                   max_attempts, replay_requested,
                   batch_attempt_key, batch_descriptor_json
            FROM l2_projection_jobs
            WHERE status IN ('queued', 'running')
              AND batch_attempt_key IN ({placeholders})
            """,
            tuple(attempt_keys),
        ) as cursor:
            for row in await cursor.fetchall():
                rows_by_event[str(row["event_id"])] = row

    grouped: dict[str, list[aiosqlite.Row]] = {}
    for row in rows_by_event.values():
        attempt_key = str(row["batch_attempt_key"] or "").strip()
        group_key = f"batch:{attempt_key}" if attempt_key else f"event:{row['event_id']}"
        grouped.setdefault(group_key, []).append(row)

    result: list[tuple[list[aiosqlite.Row], bool]] = []
    for group_key in sorted(grouped):
        rows = sorted(grouped[group_key], key=lambda row: str(row["event_id"]))
        attempt_key = str(rows[0]["batch_attempt_key"] or "").strip()
        if not attempt_key:
            # A claimed row is not an attempt until the final worker batch has
            # been bound. Recovery must release this lease without consuming
            # retry budget or inventing singleton terminal lineage.
            descriptor_valid = False
        else:
            try:
                await assert_bound_projection_attempt(
                    db,
                    tuple(_lease_from_active_row(row) for row in rows),
                    allowed_statuses=("queued", "running"),
                )
                descriptor_valid = True
            except ProjectionAttemptFencedError:
                descriptor_valid = False
        result.append((rows, descriptor_valid))
    return result


async def _release_failed_batch_binding(
    db: aiosqlite.Connection,
    *,
    leases: list[L2ProjectionLease],
    consumer_name: str,
    attempt_key: str,
    descriptor_json: str,
    now: float,
) -> int:
    """Release only this caller's unbound/provisionally bound queued rows."""

    for lease in leases:
        async with db.execute(
            """
            SELECT status, batch_attempt_key, batch_descriptor_json
            FROM l2_projection_jobs
            WHERE event_id = ? AND claimed_by = ?
              AND lease_token = ? AND attempt_count = ?
            """,
            (
                lease.event_id,
                consumer_name,
                lease.lease_token,
                lease.attempt_count,
            ),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            continue
        if str(row[0]) != "queued":
            return -1
        persisted_key = str(row[1] or "").strip()
        persisted_descriptor = str(row[2] or "").strip()
        if (persisted_key or persisted_descriptor) and (
            persisted_key != attempt_key or persisted_descriptor != descriptor_json
        ):
            return -1

    released = 0
    for lease in leases:
        cursor = await db.execute(
            """
            UPDATE l2_projection_jobs
            SET status = 'pending',
                attempt_count = CASE
                    WHEN replay_requested = 1 THEN 0
                    ELSE MAX(attempt_count - 1, 0)
                END,
                lease_token = NULL, lease_heartbeat_at = NULL,
                batch_attempt_key = NULL, batch_descriptor_json = NULL,
                batch_bound_at = NULL,
                next_retry_at = NULL, terminal_at = NULL,
                replay_requested = 0,
                claimed_by = NULL, claimed_at = NULL,
                started_at = NULL, completed_at = NULL,
                last_error = CASE
                    WHEN replay_requested = 1 THEN NULL
                    ELSE 'projection_batch_invalidated_before_binding'
                END,
                updated_at = ?
            WHERE event_id = ? AND status = 'queued'
              AND claimed_by = ? AND lease_token = ? AND attempt_count = ?
              AND (
                  (batch_attempt_key IS NULL AND batch_descriptor_json IS NULL)
                  OR
                  (batch_attempt_key = ? AND batch_descriptor_json = ?)
              )
            """,
            (
                now,
                lease.event_id,
                consumer_name,
                lease.lease_token,
                lease.attempt_count,
                attempt_key,
                descriptor_json,
            ),
        )
        released += max(int(cursor.rowcount or 0), 0)
    return released


def _retry_delay_seconds(attempt_count: int) -> float:
    return min(300.0, 2.0 ** max(0, int(attempt_count) - 1))
