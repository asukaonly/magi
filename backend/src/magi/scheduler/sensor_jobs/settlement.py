"""Sensor sync job settlement for the scheduler repository."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Optional, cast
import uuid

from ..contracts import ScheduledExecutionResult
from .contracts import (
    SensorSyncSuccessSettlement,
    _SensorJobRepositoryHost,
)


def _continuation_identifiers(parent_job_id: str) -> tuple[str, str]:
    continuation_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"magi:sensor-sync-continuation:{parent_job_id}",
    ).hex
    return (
        f"sensor_sync_job_{continuation_id}",
        f"exec_{continuation_id}",
    )


def _continuation_payload(job: Mapping[str, Any]) -> dict[str, object]:
    payload = json.loads(str(job["payload_json"]) or "{}")
    continuation_payload: dict[str, object] = {
        "plugin_id": str(job["plugin_id"]),
        "source_type": str(job["source_type"]),
        "manual": bool(job["manual"]),
    }
    if isinstance(payload, dict) and isinstance(payload.get("sync_request"), dict):
        continuation_payload["sync_request"] = dict(payload["sync_request"])
    return continuation_payload


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
        continue_sync: bool,
    ) -> SensorSyncSuccessSettlement:
        """Atomically commit success and admit any required continuation."""

        host = cast(_SensorJobRepositoryHost, self)
        completed_at = float(finished_at)
        stats_json = json.dumps(result.stats, ensure_ascii=False)
        continuation_job_id, continuation_execution_id = _continuation_identifiers(job_id)
        async with host._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                job_cursor = await db.execute(
                    """
                    SELECT
                        execution_id,
                        target_type,
                        target_key,
                        plugin_id,
                        source_type,
                        manual,
                        payload_json,
                        status
                    FROM sensor_sync_jobs
                    WHERE job_id = ?
                    """,
                    (job_id,),
                )
                job = await job_cursor.fetchone()
                if job is None:
                    raise RuntimeError(f"Sensor sync job not found: {job_id}")
                if str(job["status"]) == "success":
                    continuation_cursor = await db.execute(
                        """
                        SELECT execution_id
                        FROM sensor_sync_jobs
                        WHERE job_id = ?
                        """,
                        (continuation_job_id,),
                    )
                    continuation = await continuation_cursor.fetchone()
                    if continue_sync != (continuation is not None):
                        raise RuntimeError(
                            "Sensor sync continuation contract changed after success: "
                            f"{job_id}"
                        )
                    await db.rollback()
                    return SensorSyncSuccessSettlement(
                        committed=False,
                        continuation_job_id=(
                            continuation_job_id if continuation is not None else None
                        ),
                        continuation_execution_id=(
                            str(continuation["execution_id"])
                            if continuation is not None
                            else None
                        ),
                    )
                if str(job["status"]) != "running":
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
                    SET running = ?,
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
                        1 if continue_sync else 0,
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
                    raise RuntimeError(
                        f"Sensor sync success settlement lost state for job: {job_id}"
                    )

                if continue_sync:
                    continuation_schedule_id = (
                        "sensor-sync-continuation:"
                        f"{job['plugin_id']}:{job['source_type']}:{job_id}"
                    )
                    await db.execute(
                        """
                        INSERT INTO schedule_executions (
                            execution_id,
                            schedule_id,
                            target_type,
                            target_key,
                            manual,
                            status,
                            started_at,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                        """,
                        (
                            continuation_execution_id,
                            continuation_schedule_id,
                            str(job["target_type"]),
                            str(job["target_key"]),
                            1 if bool(job["manual"]) else 0,
                            completed_at,
                            completed_at,
                        ),
                    )
                    await db.execute(
                        """
                        INSERT INTO sensor_sync_jobs (
                            job_id,
                            schedule_id,
                            execution_id,
                            target_type,
                            target_key,
                            plugin_id,
                            source_type,
                            manual,
                            status,
                            payload_json,
                            next_attempt_at,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                        """,
                        (
                            continuation_job_id,
                            continuation_schedule_id,
                            continuation_execution_id,
                            str(job["target_type"]),
                            str(job["target_key"]),
                            str(job["plugin_id"]),
                            str(job["source_type"]),
                            1 if bool(job["manual"]) else 0,
                            json.dumps(
                                _continuation_payload(job),
                                ensure_ascii=False,
                            ),
                            completed_at,
                            completed_at,
                        ),
                    )
                await db.commit()
                return SensorSyncSuccessSettlement(
                    committed=True,
                    continuation_job_id=(
                        continuation_job_id if continue_sync else None
                    ),
                    continuation_execution_id=(
                        continuation_execution_id if continue_sync else None
                    ),
                )
            except BaseException:
                await db.rollback()
                raise
