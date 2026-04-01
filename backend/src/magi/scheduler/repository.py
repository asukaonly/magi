"""SQLite-backed persistence for the unified scheduler runtime."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import aiosqlite

from ..core.sqlite import connect_aiosqlite

from .contracts import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)


class ScheduleRepository:
    """Persistence layer for scheduler definitions and runtime target state."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(Path(db_path).expanduser())

    @asynccontextmanager
    async def _connect(self):
        db = await connect_aiosqlite(self._db_path)
        try:
            yield db
        finally:
            await db.close()

    async def initialize(self) -> None:
        async with self._connect() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    trigger_config TEXT NOT NULL,
                    target_payload TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    job_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS target_state (
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    running INTEGER NOT NULL DEFAULT 0,
                    last_run_at REAL,
                    last_success_at REAL,
                    last_error TEXT,
                    last_cursor TEXT,
                    watermark_ts REAL,
                    next_run_at REAL,
                    scheduler_job_id TEXT,
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (target_type, target_key)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_executions (
                    execution_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    manual INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    duration_ms REAL,
                    result_message TEXT,
                    error TEXT,
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    next_cursor TEXT,
                    watermark_ts REAL,
                    scheduler_job_id TEXT,
                    created_at REAL NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_sync_jobs (
                    job_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    manual INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    claimed_at REAL,
                    started_at REAL,
                    finished_at REAL,
                    claimed_by TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    result_message TEXT,
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    next_cursor TEXT,
                    watermark_ts REAL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_executions_schedule_id ON schedule_executions(schedule_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_executions_target ON schedule_executions(target_type, target_key)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_executions_started_at ON schedule_executions(started_at DESC)"
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sensor_sync_jobs_status_created
                ON sensor_sync_jobs(status, created_at ASC)
                """
            )
            await db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sensor_sync_jobs_one_outstanding_per_target
                ON sensor_sync_jobs(target_type, target_key)
                WHERE status IN ('queued', 'running')
                """
            )
            await db.commit()

    async def reset_running_flags(self) -> None:
        async with self._connect() as db:
            await db.execute("UPDATE target_state SET running = 0")
            await db.commit()

    async def upsert_schedule(self, definition: ScheduleDefinition) -> None:
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO schedules (
                    schedule_id, target_type, target_key, trigger_type, trigger_config,
                    target_payload, metadata, enabled, job_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    target_type = excluded.target_type,
                    target_key = excluded.target_key,
                    trigger_type = excluded.trigger_type,
                    trigger_config = excluded.trigger_config,
                    target_payload = excluded.target_payload,
                    metadata = excluded.metadata,
                    enabled = excluded.enabled,
                    job_id = excluded.job_id,
                    updated_at = excluded.updated_at
                """,
                (
                    definition.schedule_id,
                    definition.target_type.value,
                    definition.target_key,
                    definition.trigger.trigger_type.value,
                    json.dumps(definition.trigger.config, ensure_ascii=False),
                    json.dumps(definition.target_payload, ensure_ascii=False),
                    json.dumps(definition.metadata, ensure_ascii=False),
                    1 if definition.enabled else 0,
                    definition.job_id,
                    now,
                    now,
                ),
            )
            await db.execute(
                """
                INSERT INTO target_state (target_type, target_key, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(target_type, target_key) DO NOTHING
                """,
                (definition.target_type.value, definition.target_key, now),
            )
            await db.commit()

    async def get_schedule(self, schedule_id: str) -> Optional[ScheduleDefinition]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT schedule_id, target_type, target_key, trigger_type, trigger_config,
                       target_payload, metadata, enabled, job_id
                FROM schedules
                WHERE schedule_id = ?
                """,
                (schedule_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_schedule(row)

    async def get_recurring_target_binding(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> Optional[tuple[str, float | None]]:
        """Return the active recurring job binding for a target, if any."""

        async with self._connect() as db:
            jobs_table_cursor = await db.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'apscheduler_jobs'
                LIMIT 1
                """
            )
            has_apscheduler_jobs = await jobs_table_cursor.fetchone() is not None
            jobs_join = (
                "LEFT JOIN apscheduler_jobs AS j ON j.id = COALESCE(s.job_id, s.schedule_id)"
                if has_apscheduler_jobs
                else ""
            )
            next_run_select = "j.next_run_time" if has_apscheduler_jobs else "NULL"
            cursor = await db.execute(
                f"""
                SELECT
                    COALESCE(s.job_id, s.schedule_id) AS job_binding_id,
                    {next_run_select}
                FROM schedules AS s
                {jobs_join}
                WHERE s.target_type = ?
                  AND s.target_key = ?
                  AND s.enabled = 1
                  AND s.trigger_type != 'once'
                ORDER BY s.updated_at DESC
                LIMIT 1
                """,
                (target_type.value, target_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0]), float(row[1]) if row[1] is not None else None

    async def list_schedules(self, *, enabled_only: bool = False) -> list[ScheduleDefinition]:
        query = (
            "SELECT schedule_id, target_type, target_key, trigger_type, trigger_config, "
            "target_payload, metadata, enabled, job_id FROM schedules"
        )
        params: tuple[object, ...] = ()
        if enabled_only:
            query += " WHERE enabled = 1"
        async with self._connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        return [self._row_to_schedule(row) for row in rows]

    async def delete_schedule(self, schedule_id: str) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,))
            await db.commit()

    async def update_schedule_binding(
        self,
        schedule_id: str,
        *,
        job_id: Optional[str],
        next_run_at: Optional[float],
    ) -> None:
        schedule = await self.get_schedule(schedule_id)
        if schedule is None:
            return
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                "UPDATE schedules SET job_id = ?, updated_at = ? WHERE schedule_id = ?",
                (job_id, now, schedule_id),
            )
            await db.execute(
                """
                INSERT INTO target_state (
                    target_type, target_key, next_run_at, scheduler_job_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(target_type, target_key) DO UPDATE SET
                    next_run_at = excluded.next_run_at,
                    scheduler_job_id = excluded.scheduler_job_id,
                    updated_at = excluded.updated_at
                """,
                (
                    schedule.target_type.value,
                    schedule.target_key,
                    next_run_at,
                    job_id,
                    now,
                ),
            )
            await db.commit()

    async def get_target_state(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> ScheduledTargetState:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT running, last_run_at, last_success_at, last_error, last_cursor,
                       watermark_ts, next_run_at, scheduler_job_id, stats_json, updated_at
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
        return ScheduledTargetState(
            target_type=target_type,
            target_key=target_key,
            running=bool(row[0]),
            last_run_at=row[1],
            last_success_at=row[2],
            last_error=row[3],
            last_cursor=row[4],
            watermark_ts=row[5],
            next_run_at=row[6],
            scheduler_job_id=row[7],
            stats=json.loads(row[8] or "{}"),
            updated_at=row[9],
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
        next_run_at: Optional[float],
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
                    next_run_at = ?,
                    scheduler_job_id = ?,
                    stats_json = ?,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (
                    now,
                    result.next_cursor,
                    result.watermark_ts,
                    next_run_at,
                    scheduler_job_id,
                    json.dumps(result.stats, ensure_ascii=False),
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
        next_run_at: Optional[float],
        scheduler_job_id: Optional[str],
    ) -> None:
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE target_state
                SET running = 0,
                    last_error = ?,
                    next_run_at = ?,
                    scheduler_job_id = ?,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (
                    error,
                    next_run_at,
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
                SET next_run_at = NULL,
                    scheduler_job_id = NULL,
                    running = 0,
                    last_error = NULL,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (now, target_type.value, target_key),
            )
            await db.commit()

    async def create_execution_record(
        self,
        *,
        schedule_id: str,
        target_type: ScheduledTargetType,
        target_key: str,
        manual: bool,
        started_at: float,
    ) -> str:
        execution_id = f"exec_{uuid.uuid4().hex}"
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO schedule_executions (
                    execution_id, schedule_id, target_type, target_key, manual, status,
                    started_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    execution_id,
                    schedule_id,
                    target_type.value,
                    target_key,
                    1 if manual else 0,
                    started_at,
                    started_at,
                ),
            )
            await db.commit()
        return execution_id

    async def enqueue_sensor_sync_job(
        self,
        *,
        schedule: ScheduleDefinition,
        execution_id: str,
        manual: bool,
    ) -> Optional[str]:
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
            async with self._connect() as db:
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
        async with self._connect() as db:
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
        async with self._connect() as db:
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

    async def claim_next_sensor_sync_job(self, *, claimed_by: str) -> Optional[dict[str, object]]:
        now = time.time()
        async with self._connect() as db:
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
        cutoff = time.time() - float(running_timeout_seconds)
        async with self._connect() as db:
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
        async with self._connect() as db:
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
        async with self._connect() as db:
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

    async def complete_execution_success(
        self,
        execution_id: str,
        *,
        result: ScheduledExecutionResult,
        scheduler_job_id: Optional[str],
        finished_at: float,
    ) -> None:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT started_at FROM schedule_executions WHERE execution_id = ?",
                (execution_id,),
            )
            row = await cursor.fetchone()
            started_at = float(row[0]) if row and row[0] is not None else finished_at
            await db.execute(
                """
                UPDATE schedule_executions
                SET status = 'success',
                    finished_at = ?,
                    duration_ms = ?,
                    result_message = ?,
                    stats_json = ?,
                    next_cursor = ?,
                    watermark_ts = ?,
                    scheduler_job_id = ?
                WHERE execution_id = ?
                """,
                (
                    finished_at,
                    max(0.0, (finished_at - started_at) * 1000.0),
                    result.message,
                    json.dumps(result.stats, ensure_ascii=False),
                    result.next_cursor,
                    result.watermark_ts,
                    scheduler_job_id,
                    execution_id,
                ),
            )
            await db.commit()

    async def complete_execution_failure(
        self,
        execution_id: str,
        *,
        error: str,
        scheduler_job_id: Optional[str],
        finished_at: float,
    ) -> None:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT started_at FROM schedule_executions WHERE execution_id = ?",
                (execution_id,),
            )
            row = await cursor.fetchone()
            started_at = float(row[0]) if row and row[0] is not None else finished_at
            await db.execute(
                """
                UPDATE schedule_executions
                SET status = 'failed',
                    finished_at = ?,
                    duration_ms = ?,
                    error = ?,
                    scheduler_job_id = ?
                WHERE execution_id = ?
                """,
                (
                    finished_at,
                    max(0.0, (finished_at - started_at) * 1000.0),
                    error,
                    scheduler_job_id,
                    execution_id,
                ),
            )
            await db.commit()

    def _row_to_schedule(self, row: tuple[object, ...]) -> ScheduleDefinition:
        return ScheduleDefinition(
            schedule_id=str(row[0]),
            target_type=ScheduledTargetType(str(row[1])),
            target_key=str(row[2]),
            trigger=TriggerDefinition(
                trigger_type=TriggerType(str(row[3])),
                config=json.loads(str(row[4]) or "{}"),
            ),
            target_payload=json.loads(str(row[5]) or "{}"),
            metadata=json.loads(str(row[6]) or "{}"),
            enabled=bool(row[7]),
            job_id=str(row[8]) if row[8] is not None else None,
        )

    async def list_executions(
        self,
        *,
        schedule_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Return recent execution records, optionally filtered by schedule_id."""
        if schedule_id:
            query = (
                "SELECT execution_id, schedule_id, target_type, target_key, manual, "
                "status, started_at, finished_at, duration_ms, result_message, error, "
                "stats_json, next_cursor, watermark_ts, scheduler_job_id, created_at "
                "FROM schedule_executions WHERE schedule_id = ? "
                "ORDER BY started_at DESC LIMIT ?"
            )
            params: tuple[object, ...] = (schedule_id, limit)
        else:
            query = (
                "SELECT execution_id, schedule_id, target_type, target_key, manual, "
                "status, started_at, finished_at, duration_ms, result_message, error, "
                "stats_json, next_cursor, watermark_ts, scheduler_job_id, created_at "
                "FROM schedule_executions ORDER BY started_at DESC LIMIT ?"
            )
            params = (limit,)
        async with self._connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            results.append({
                "execution_id": str(row[0]),
                "schedule_id": str(row[1]),
                "target_type": str(row[2]),
                "target_key": str(row[3]),
                "manual": bool(row[4]),
                "status": str(row[5]),
                "started_at": float(row[6]) if row[6] is not None else None,
                "finished_at": float(row[7]) if row[7] is not None else None,
                "duration_ms": float(row[8]) if row[8] is not None else None,
                "result_message": str(row[9]) if row[9] is not None else None,
                "error": str(row[10]) if row[10] is not None else None,
                "stats": json.loads(str(row[11]) or "{}"),
                "next_cursor": str(row[12]) if row[12] is not None else None,
                "watermark_ts": float(row[13]) if row[13] is not None else None,
                "scheduler_job_id": str(row[14]) if row[14] is not None else None,
                "created_at": float(row[15]) if row[15] is not None else None,
            })
        return results

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
