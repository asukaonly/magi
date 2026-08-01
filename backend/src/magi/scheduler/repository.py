"""SQLite-backed persistence for the unified scheduler runtime."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import time
from pathlib import Path
from typing import Optional

from ..core.sqlite import connect_aiosqlite

from .contracts import (
    ScheduleDefinition,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from .execution_repository import SchedulerExecutionRepositoryMixin
from .sensor_jobs import SensorSyncJobRepositoryMixin
from .target_state_repository import SchedulerTargetStateRepositoryMixin


class ScheduleRepository(
    SchedulerTargetStateRepositoryMixin,
    SchedulerExecutionRepositoryMixin,
    SensorSyncJobRepositoryMixin,
):
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
            await db.commit()

    async def reset_running_flags(self) -> None:
        async with self._connect() as db:
            await db.execute("UPDATE target_state SET running = 0")
            await db.commit()

    async def clear_user_data(self) -> dict[str, int]:
        """Erase user-owned schedules and scheduler-generated content."""

        now = time.time()
        user_target_type = ScheduledTargetType.USER_AGENT_TASK.value
        async with self._connect() as db:
            await db.execute("PRAGMA secure_delete=ON")
            await db.execute("BEGIN IMMEDIATE")
            try:
                jobs_table_cursor = await db.execute("""
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'apscheduler_jobs'
                    LIMIT 1
                    """)
                has_jobs_table = await jobs_table_cursor.fetchone() is not None
                user_jobs = 0
                if has_jobs_table:
                    jobs_cursor = await db.execute(
                        """
                        DELETE FROM apscheduler_jobs
                        WHERE id IN (
                            SELECT COALESCE(job_id, schedule_id)
                            FROM schedules
                            WHERE target_type = ?
                        )
                        """,
                        (user_target_type,),
                    )
                    user_jobs = max(0, int(jobs_cursor.rowcount or 0))
                sensor_jobs_cursor = await db.execute("DELETE FROM sensor_sync_jobs")
                await db.execute(
                    """
                    UPDATE target_state
                    SET running = 0,
                        updated_at = ?
                    WHERE target_type = ?
                    """,
                    (now, ScheduledTargetType.SENSOR_SYNC.value),
                )
                executions_cursor = await db.execute("DELETE FROM schedule_executions")
                user_states_cursor = await db.execute(
                    "DELETE FROM target_state WHERE target_type = ?",
                    (user_target_type,),
                )
                user_schedules_cursor = await db.execute(
                    "DELETE FROM schedules WHERE target_type = ?",
                    (user_target_type,),
                )
                sanitized_states_cursor = await db.execute(
                    """
                    UPDATE target_state
                    SET last_error = NULL,
                        stats_json = '{}',
                        updated_at = ?
                    WHERE last_error IS NOT NULL OR stats_json != '{}'
                    """,
                    (now,),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
            checkpoint_cursor = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            checkpoint = await checkpoint_cursor.fetchone()
            if checkpoint is not None and int(checkpoint[0] or 0) != 0:
                raise RuntimeError("Scheduler database WAL could not be truncated after clear")
        return {
            "user_schedules": max(0, int(user_schedules_cursor.rowcount or 0)),
            "user_target_states": max(0, int(user_states_cursor.rowcount or 0)),
            "user_jobs": user_jobs,
            "sensor_jobs": max(0, int(sensor_jobs_cursor.rowcount or 0)),
            "executions": max(0, int(executions_cursor.rowcount or 0)),
            "sanitized_target_states": max(
                0,
                int(sanitized_states_cursor.rowcount or 0),
            ),
        }

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

    async def get_schedule_runtime_state(self, schedule: ScheduleDefinition) -> ScheduledTargetState:
        """Return row-display runtime state for one schedule definition.

        Targets can be shared by several schedules for locking/coalescing, so
        target_state is not specific enough for per-schedule table columns.
        """

        job_id = schedule.job_id or schedule.schedule_id
        base_state = await self.get_target_state(schedule.target_type, schedule.target_key)
        executions = await self.list_executions(schedule_id=schedule.schedule_id, limit=1)
        # next_run_at is exclusively sourced from the APScheduler jobstore (#89).
        # target_state no longer persists next_run_at.
        next_run_at = await self.get_schedule_next_run_at(schedule)
        if not executions:
            return ScheduledTargetState(
                target_type=schedule.target_type,
                target_key=schedule.target_key,
                running=base_state.running,
                next_run_at=next_run_at,
                scheduler_job_id=job_id,
                updated_at=base_state.updated_at,
            )

        latest = executions[0]
        status = str(latest.get("status") or "")
        started_at = latest.get("started_at") if isinstance(latest.get("started_at"), (int, float)) else None
        finished_at = latest.get("finished_at") if isinstance(latest.get("finished_at"), (int, float)) else None
        stats = latest.get("stats") if isinstance(latest.get("stats"), dict) else {}
        error = latest.get("error") if isinstance(latest.get("error"), str) else None
        return ScheduledTargetState(
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            running=base_state.running,
            last_run_at=float(started_at) if started_at is not None else None,
            last_success_at=float(finished_at) if status == "success" and finished_at is not None else None,
            last_error=error,
            next_run_at=next_run_at,
            scheduler_job_id=str(latest.get("scheduler_job_id") or job_id),
            stats=dict(stats),
            updated_at=float(finished_at or started_at or base_state.updated_at or time.time()),
        )

    async def get_schedule_next_run_at(self, schedule: ScheduleDefinition) -> float | None:
        job_id = schedule.job_id or schedule.schedule_id
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
            if not has_apscheduler_jobs:
                return None
            cursor = await db.execute(
                "SELECT next_run_time FROM apscheduler_jobs WHERE id = ?",
                (job_id,),
            )
            row = await cursor.fetchone()
        return float(row[0]) if row is not None and row[0] is not None else None

    async def delete_schedule(self, schedule_id: str) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,))
            await db.commit()

    async def update_schedule_binding(
        self,
        schedule_id: str,
        *,
        job_id: Optional[str],
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
                    target_type, target_key, scheduler_job_id, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(target_type, target_key) DO UPDATE SET
                    scheduler_job_id = excluded.scheduler_job_id,
                    updated_at = excluded.updated_at
                """,
                (
                    schedule.target_type.value,
                    schedule.target_key,
                    job_id,
                    now,
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
