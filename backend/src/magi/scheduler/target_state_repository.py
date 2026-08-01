"""Target state persistence operations for scheduler repository."""

from __future__ import annotations

import json
import time
from typing import Optional

from .contracts import ScheduledExecutionResult, ScheduledTargetState, ScheduledTargetType


class SchedulerTargetStateRepositoryMixin:
    """Persist scheduler target locks, cursors, success, and failure state."""

    async def get_target_state(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> ScheduledTargetState:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT running, last_run_at, last_success_at, last_error, last_cursor,
                       watermark_ts, scheduler_job_id, stats_json, updated_at
                FROM target_state
                WHERE target_type = ? AND target_key = ?
                """,
                (target_type.value, target_key),
            )
            row = await cursor.fetchone()
            if row is None:
                now = time.time()
                await db.execute(
                    """
                    INSERT INTO target_state (target_type, target_key, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (target_type.value, target_key, now),
                )
                await db.commit()
                return ScheduledTargetState(
                    target_type=target_type,
                    target_key=target_key,
                    updated_at=now,
                )
        # Column mapping (next_run_at column dropped from SELECT — jobstore is authoritative):
        # row[0] = running
        # row[1] = last_run_at
        # row[2] = last_success_at
        # row[3] = last_error
        # row[4] = last_cursor
        # row[5] = watermark_ts
        # row[6] = scheduler_job_id   (was row[7] before next_run_at removal)
        # row[7] = stats_json          (was row[8])
        # row[8] = updated_at          (was row[9])
        return ScheduledTargetState(
            target_type=target_type,
            target_key=target_key,
            running=bool(row[0]),
            last_run_at=row[1],
            last_success_at=row[2],
            last_error=row[3],
            last_cursor=row[4],
            watermark_ts=row[5],
            next_run_at=None,  # not persisted; populated by get_schedule_runtime_state from jobstore
            scheduler_job_id=row[6],
            stats=json.loads(row[7] or "{}"),
            updated_at=row[8],
        )

    async def acquire_target_lock(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> bool:
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO target_state (target_type, target_key, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(target_type, target_key) DO NOTHING
                """,
                (target_type.value, target_key, now),
            )
            cursor = await db.execute(
                """
                UPDATE target_state
                SET running = 1, last_run_at = ?, updated_at = ?
                WHERE target_type = ? AND target_key = ? AND running = 0
                """,
                (now, now, target_type.value, target_key),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def record_target_success(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
        *,
        result: ScheduledExecutionResult,
        scheduler_job_id: Optional[str],
    ) -> None:
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE target_state
                SET running = 0,
                    last_success_at = ?,
                    last_error = NULL,
                    last_cursor = ?,
                    watermark_ts = ?,
                    scheduler_job_id = ?,
                    stats_json = ?,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (
                    now,
                    result.next_cursor,
                    result.watermark_ts,
                    scheduler_job_id,
                    json.dumps(result.stats, ensure_ascii=False),
                    now,
                    target_type.value,
                    target_key,
                ),
            )
            await db.commit()

    async def update_target_cursor(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
        *,
        cursor: str,
        watermark_ts: float | None = None,
    ) -> None:
        """Persist a partial cursor without marking the target as completed."""
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE target_state
                SET last_cursor = ?,
                    watermark_ts = COALESCE(?, watermark_ts),
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (
                    cursor,
                    watermark_ts,
                    now,
                    target_type.value,
                    target_key,
                ),
            )
            await db.commit()

    async def record_target_failure(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
        *,
        error: str,
        scheduler_job_id: Optional[str],
    ) -> None:
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE target_state
                SET running = 0,
                    last_error = ?,
                    scheduler_job_id = ?,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (
                    error,
                    scheduler_job_id,
                    now,
                    target_type.value,
                    target_key,
                ),
            )
            await db.commit()

    async def clear_target_schedule_binding(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> None:
        """Clear scheduler metadata and stale errors when a recurring schedule is removed."""
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE target_state
                SET scheduler_job_id = NULL,
                    running = 0,
                    last_error = NULL,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (now, target_type.value, target_key),
            )
            await db.commit()

    async def release_target_after_data_clear(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> None:
        """Release a stale handler without restoring cleared result content."""

        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE target_state
                SET running = 0,
                    last_error = NULL,
                    stats_json = '{}',
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (now, target_type.value, target_key),
            )
            await db.commit()


__all__ = ["SchedulerTargetStateRepositoryMixin"]
