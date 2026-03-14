"""SQLite-backed persistence for the unified scheduler runtime."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import aiosqlite

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
        db = await aiosqlite.connect(self._db_path, timeout=30.0)
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("PRAGMA busy_timeout = 30000")
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
                "CREATE INDEX IF NOT EXISTS idx_schedule_executions_schedule_id ON schedule_executions(schedule_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_executions_target ON schedule_executions(target_type, target_key)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_executions_started_at ON schedule_executions(started_at DESC)"
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
