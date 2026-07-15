"""Sensor sync job queue persistence for the scheduler repository."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional, Protocol, cast

import aiosqlite

from .contracts import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
)


class _SensorJobRepositoryHost(Protocol):
    def _connect(self) -> Any: ...


class SensorSyncJobRepositoryMixin:
    """Queue, claim, and complete sensor sync jobs."""

    async def enqueue_sensor_sync_job(
        self,
        *,
        schedule: ScheduleDefinition,
        execution_id: str,
        manual: bool,
    ) -> Optional[str]:
        host = cast(_SensorJobRepositoryHost, self)
        plugin_id = str(
            schedule.target_payload.get("plugin_id")
            or schedule.metadata.get("plugin_id")
            or ""
        )
        source_type = str(
            schedule.target_payload.get("source_type")
            or schedule.metadata.get("source_type")
            or ""
        )
        if not plugin_id or not source_type:
            raise ValueError("sensor_sync job requires plugin_id and source_type")
        job_id = f"sensor_sync_job_{uuid.uuid4().hex}"
        now = time.time()
        try:
            async with host._connect() as db:
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
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        job_id,
                        schedule.schedule_id,
                        execution_id,
                        schedule.target_type.value,
                        schedule.target_key,
                        plugin_id,
                        source_type,
                        1 if manual else 0,
                        json.dumps(schedule.target_payload, ensure_ascii=False),
                        now,
                    ),
                )
                await db.commit()
        except aiosqlite.IntegrityError:
            return None
        return job_id

    async def get_sensor_sync_job(self, job_id: str) -> Optional[dict[str, object]]:
        host = cast(_SensorJobRepositoryHost, self)
        async with host._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM sensor_sync_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_sensor_sync_job(row)

    async def get_outstanding_sensor_sync_job(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> Optional[dict[str, object]]:
        host = cast(_SensorJobRepositoryHost, self)
        async with host._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM sensor_sync_jobs
                WHERE target_type = ?
                  AND target_key = ?
                  AND status IN ('queued', 'running')
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (target_type.value, target_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_sensor_sync_job(row)

    async def get_latest_sensor_sync_job(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> Optional[dict[str, object]]:
        """Return the most recently created sync job for one sensor target."""

        host = cast(_SensorJobRepositoryHost, self)
        async with host._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM sensor_sync_jobs
                WHERE target_type = ?
                  AND target_key = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (target_type.value, target_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_sensor_sync_job(row)

    async def claim_next_sensor_sync_job(self, *, claimed_by: str) -> Optional[dict[str, object]]:
        host = cast(_SensorJobRepositoryHost, self)
        now = time.time()
        async with host._connect() as db:
            cursor = await db.execute(
                """
                SELECT job_id
                FROM sensor_sync_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            job_id = str(row["job_id"])
            updated = await db.execute(
                """
                UPDATE sensor_sync_jobs
                SET status = 'running',
                    claimed_by = ?,
                    claimed_at = ?,
                    started_at = ?,
                    attempt_count = attempt_count + 1
                WHERE job_id = ?
                  AND status = 'queued'
                """,
                (claimed_by, now, now, job_id),
            )
            await db.commit()
            if updated.rowcount != 1:
                return None
        return await self.get_sensor_sync_job(job_id)

    async def requeue_stale_sensor_sync_jobs(
        self,
        *,
        running_timeout_seconds: float,
    ) -> int:
        host = cast(_SensorJobRepositoryHost, self)
        cutoff = time.time() - float(running_timeout_seconds)
        async with host._connect() as db:
            cursor = await db.execute(
                """
                UPDATE sensor_sync_jobs
                SET status = 'queued',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    started_at = NULL
                WHERE status = 'running'
                  AND started_at IS NOT NULL
                  AND started_at < ?
                """,
                (cutoff,),
            )
            await db.commit()
            return int(cursor.rowcount or 0)

    async def complete_sensor_sync_job_success(
        self,
        job_id: str,
        *,
        result: ScheduledExecutionResult,
        finished_at: float,
    ) -> None:
        host = cast(_SensorJobRepositoryHost, self)
        async with host._connect() as db:
            await db.execute(
                """
                UPDATE sensor_sync_jobs
                SET status = 'success',
                    finished_at = ?,
                    error = NULL,
                    result_message = ?,
                    stats_json = ?,
                    next_cursor = ?,
                    watermark_ts = ?
                WHERE job_id = ?
                """,
                (
                    finished_at,
                    result.message,
                    json.dumps(result.stats, ensure_ascii=False),
                    result.next_cursor,
                    result.watermark_ts,
                    job_id,
                ),
            )
            await db.commit()

    async def complete_sensor_sync_job_failure(
        self,
        job_id: str,
        *,
        error: str,
        finished_at: float,
    ) -> None:
        host = cast(_SensorJobRepositoryHost, self)
        async with host._connect() as db:
            await db.execute(
                """
                UPDATE sensor_sync_jobs
                SET status = 'failed',
                    finished_at = ?,
                    error = ?,
                    result_message = NULL
                WHERE job_id = ?
                """,
                (finished_at, error, job_id),
            )
            await db.commit()

    def _row_to_sensor_sync_job(self, row: aiosqlite.Row) -> dict[str, object]:
        return {
            "job_id": str(row["job_id"]),
            "schedule_id": str(row["schedule_id"]),
            "execution_id": str(row["execution_id"]),
            "target_type": str(row["target_type"]),
            "target_key": str(row["target_key"]),
            "plugin_id": str(row["plugin_id"]),
            "source_type": str(row["source_type"]),
            "manual": bool(row["manual"]),
            "status": str(row["status"]),
            "payload": json.loads(str(row["payload_json"]) or "{}"),
            "created_at": float(row["created_at"]),
            "claimed_at": float(row["claimed_at"]) if row["claimed_at"] is not None else None,
            "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
            "finished_at": float(row["finished_at"]) if row["finished_at"] is not None else None,
            "claimed_by": str(row["claimed_by"]) if row["claimed_by"] is not None else None,
            "attempt_count": int(row["attempt_count"] or 0),
            "error": str(row["error"]) if row["error"] is not None else None,
            "result_message": str(row["result_message"]) if row["result_message"] is not None else None,
            "stats": json.loads(str(row["stats_json"]) or "{}"),
            "next_cursor": str(row["next_cursor"]) if row["next_cursor"] is not None else None,
            "watermark_ts": float(row["watermark_ts"]) if row["watermark_ts"] is not None else None,
        }


__all__ = ["SensorSyncJobRepositoryMixin"]
