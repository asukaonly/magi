"""Sensor sync job settlement for the scheduler repository."""

from __future__ import annotations

import json
from typing import Optional, cast

from ..contracts import ScheduledExecutionResult
from .contracts import _SensorJobRepositoryHost


class _SensorSyncJobSettlementMixin:
    async def settle_sensor_sync_job_failure(
        self,
        job_id: str,
        *,
        error: str,
        failed_at: float,
        retry_delay_seconds: float,
        max_attempts: int,
        scheduler_job_id: Optional[str],
    ) -> bool:
        """Atomically retry or terminally fail one sensor-sync attempt."""

        host = cast(_SensorJobRepositoryHost, self)
        finished_at = float(failed_at)
        next_attempt_at = finished_at + max(0.0, float(retry_delay_seconds))
        bounded_error = str(error or "")[:2000]
        async with host._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            job_cursor = await db.execute(
                """
                SELECT execution_id, target_type, target_key, attempt_count
                FROM sensor_sync_jobs
                WHERE job_id = ? AND status = 'running'
                """,
                (job_id,),
            )
            job = await job_cursor.fetchone()
            if job is None:
                await db.rollback()
                raise RuntimeError(f"Running sensor sync job not found: {job_id}")
            execution_cursor = await db.execute(
                """
                SELECT started_at
                FROM schedule_executions
                WHERE execution_id = ? AND status = 'running'
                """,
                (str(job["execution_id"]),),
            )
            execution = await execution_cursor.fetchone()
            if execution is None:
                await db.rollback()
                raise RuntimeError(
                    f"Running sensor sync execution not found: {job['execution_id']}"
                )
            execution_started_at = (
                float(execution["started_at"])
                if execution["started_at"] is not None
                else finished_at
            )
            requeued = int(job["attempt_count"] or 0) < max(1, int(max_attempts))
            if requeued:
                await db.execute(
                    """
                    UPDATE sensor_sync_jobs
                    SET status = 'queued',
                        claimed_by = NULL,
                        claimed_at = NULL,
                        started_at = NULL,
                        finished_at = NULL,
                        next_attempt_at = ?,
                        error = ?,
                        result_message = NULL
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (next_attempt_at, bounded_error, job_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE sensor_sync_jobs
                    SET status = 'failed',
                        finished_at = ?,
                        next_attempt_at = ?,
                        error = ?,
                        result_message = NULL
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (finished_at, finished_at, bounded_error, job_id),
                )
                await db.execute(
                    """
                    UPDATE schedule_executions
                    SET status = 'failed',
                        finished_at = ?,
                        duration_ms = ?,
                        error = ?,
                        scheduler_job_id = ?
                    WHERE execution_id = ? AND status = 'running'
                    """,
                    (
                        finished_at,
                        max(0.0, (finished_at - execution_started_at) * 1000.0),
                        bounded_error,
                        scheduler_job_id,
                        str(job["execution_id"]),
                    ),
                )
            target_cursor = await db.execute(
                """
                UPDATE target_state
                SET running = 0,
                    last_error = ?,
                    scheduler_job_id = ?,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (
                    bounded_error,
                    scheduler_job_id,
                    finished_at,
                    str(job["target_type"]),
                    str(job["target_key"]),
                ),
            )
            if target_cursor.rowcount != 1:
                await db.rollback()
                raise RuntimeError(
                    "Sensor sync target state not found: "
                    f"{job['target_type']}:{job['target_key']}"
                )
            await db.commit()
            return requeued

    async def settle_sensor_sync_job_success(
        self,
        job_id: str,
        *,
        result: ScheduledExecutionResult,
        finished_at: float,
        scheduler_job_id: Optional[str],
    ) -> None:
        """Atomically commit sensor job, target, and execution success state."""

        host = cast(_SensorJobRepositoryHost, self)
        completed_at = float(finished_at)
        stats_json = json.dumps(result.stats, ensure_ascii=False)
        async with host._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            job_cursor = await db.execute(
                """
                SELECT execution_id, target_type, target_key
                FROM sensor_sync_jobs
                WHERE job_id = ? AND status = 'running'
                """,
                (job_id,),
            )
            job = await job_cursor.fetchone()
            if job is None:
                await db.rollback()
                raise RuntimeError(f"Running sensor sync job not found: {job_id}")
            execution_cursor = await db.execute(
                """
                SELECT started_at
                FROM schedule_executions
                WHERE execution_id = ? AND status = 'running'
                """,
                (str(job["execution_id"]),),
            )
            execution = await execution_cursor.fetchone()
            if execution is None:
                await db.rollback()
                raise RuntimeError(
                    f"Running sensor sync execution not found: {job['execution_id']}"
                )
            execution_started_at = (
                float(execution["started_at"])
                if execution["started_at"] is not None
                else completed_at
            )
            job_update = await db.execute(
                """
                UPDATE sensor_sync_jobs
                SET status = 'success',
                    finished_at = ?,
                    next_attempt_at = ?,
                    error = NULL,
                    result_message = ?,
                    stats_json = ?,
                    next_cursor = ?,
                    watermark_ts = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (
                    completed_at,
                    completed_at,
                    result.message,
                    stats_json,
                    result.next_cursor,
                    result.watermark_ts,
                    job_id,
                ),
            )
            target_update = await db.execute(
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
                    completed_at,
                    result.next_cursor,
                    result.watermark_ts,
                    scheduler_job_id,
                    stats_json,
                    completed_at,
                    str(job["target_type"]),
                    str(job["target_key"]),
                ),
            )
            execution_update = await db.execute(
                """
                UPDATE schedule_executions
                SET status = 'success',
                    finished_at = ?,
                    duration_ms = ?,
                    result_message = ?,
                    error = NULL,
                    stats_json = ?,
                    next_cursor = ?,
                    watermark_ts = ?,
                    scheduler_job_id = ?
                WHERE execution_id = ? AND status = 'running'
                """,
                (
                    completed_at,
                    max(0.0, (completed_at - execution_started_at) * 1000.0),
                    result.message,
                    stats_json,
                    result.next_cursor,
                    result.watermark_ts,
                    scheduler_job_id,
                    str(job["execution_id"]),
                ),
            )
            if (
                job_update.rowcount != 1
                or target_update.rowcount != 1
                or execution_update.rowcount != 1
            ):
                await db.rollback()
                raise RuntimeError(
                    f"Sensor sync success settlement lost state for job: {job_id}"
                )
            await db.commit()
