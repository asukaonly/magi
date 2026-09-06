"""Source sync job admission, claiming, and recovery."""

from __future__ import annotations

import json
import time
from typing import Optional, cast
import uuid

import aiosqlite

from ..contracts import ScheduleDefinition
from .contracts import SourceSyncEnqueueResult, _SourceJobRepositoryHost


class _SourceSyncJobAdmissionMixin:
    async def enqueue_source_sync_execution(
        self,
        *,
        schedule: ScheduleDefinition,
        manual: bool,
        started_at: float,
    ) -> Optional[SourceSyncEnqueueResult]:
        host = cast(_SourceJobRepositoryHost, self)
        plugin_id = str(
            schedule.target_payload.get("plugin_id") or schedule.metadata.get("plugin_id") or ""
        )
        source_type = str(
            schedule.target_payload.get("source_type") or schedule.metadata.get("source_type") or ""
        )
        if not plugin_id or not source_type:
            raise ValueError("source_sync job requires plugin_id and source_type")
        job_id = f"source_sync_job_{uuid.uuid4().hex}"
        execution_id = f"exec_{uuid.uuid4().hex}"
        admitted_at = float(started_at)
        try:
            async with host._connect() as db:
                await db.execute("BEGIN IMMEDIATE")
                outstanding_cursor = await db.execute(
                    """
                    SELECT 1
                    FROM source_sync_jobs
                    WHERE target_type = ?
                      AND target_key = ?
                      AND status IN ('queued', 'running')
                    LIMIT 1
                    """,
                    (schedule.target_type.value, schedule.target_key),
                )
                if await outstanding_cursor.fetchone() is not None:
                    await db.rollback()
                    return None
                await db.execute(
                    """
                    INSERT INTO target_state (target_type, target_key, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(target_type, target_key) DO NOTHING
                    """,
                    (
                        schedule.target_type.value,
                        schedule.target_key,
                        admitted_at,
                    ),
                )
                lock_cursor = await db.execute(
                    """
                    UPDATE target_state
                    SET running = 1,
                        last_run_at = ?,
                        updated_at = ?
                    WHERE target_type = ?
                      AND target_key = ?
                      AND running = 0
                    """,
                    (
                        admitted_at,
                        admitted_at,
                        schedule.target_type.value,
                        schedule.target_key,
                    ),
                )
                if lock_cursor.rowcount != 1:
                    await db.rollback()
                    return None
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
                        execution_id,
                        schedule.schedule_id,
                        schedule.target_type.value,
                        schedule.target_key,
                        1 if manual else 0,
                        admitted_at,
                        admitted_at,
                    ),
                )
                await db.execute(
                    """
                    INSERT INTO source_sync_jobs (
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
                        job_id,
                        schedule.schedule_id,
                        execution_id,
                        schedule.target_type.value,
                        schedule.target_key,
                        plugin_id,
                        source_type,
                        1 if manual else 0,
                        json.dumps(schedule.target_payload, ensure_ascii=False),
                        admitted_at,
                        admitted_at,
                    ),
                )
                await db.commit()
        except aiosqlite.IntegrityError:
            return None
        return SourceSyncEnqueueResult(
            job_id=job_id,
            execution_id=execution_id,
        )

    async def claim_next_source_sync_job(self, *, claimed_by: str) -> Optional[dict[str, object]]:
        host = cast(_SourceJobRepositoryHost, self)
        now = time.time()
        async with host._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT job_id, target_type, target_key
                FROM source_sync_jobs
                WHERE status = 'queued'
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, created_at ASC
                LIMIT 1
                """,
                (now,),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                return None
            job_id = str(row["job_id"])
            updated = await db.execute(
                """
                UPDATE source_sync_jobs
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
            if updated.rowcount != 1:
                await db.rollback()
                return None
            target_update = await db.execute(
                """
                UPDATE target_state
                SET running = 1,
                    last_run_at = ?,
                    updated_at = ?
                WHERE target_type = ? AND target_key = ?
                """,
                (
                    now,
                    now,
                    str(row["target_type"]),
                    str(row["target_key"]),
                ),
            )
            if target_update.rowcount != 1:
                await db.rollback()
                raise RuntimeError(
                    "Source sync target state not found while claiming job: "
                    f"{row['target_type']}:{row['target_key']}"
                )
            await db.commit()
        return await host.get_source_sync_job(job_id)

    async def recover_running_source_sync_jobs(self) -> int:
        """Make every interrupted running job immediately claimable on startup."""

        host = cast(_SourceJobRepositoryHost, self)
        now = time.time()
        async with host._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                UPDATE target_state
                SET running = 0,
                    last_error = 'SOURCE_SYNC_EXECUTOR_RESTARTED',
                    updated_at = ?
                WHERE EXISTS (
                    SELECT 1
                    FROM source_sync_jobs AS job
                    WHERE job.status = 'running'
                      AND job.target_type = target_state.target_type
                      AND job.target_key = target_state.target_key
                )
                """,
                (now,),
            )
            cursor = await db.execute(
                """
                UPDATE source_sync_jobs
                SET status = 'queued',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    next_attempt_at = ?,
                    error = 'SOURCE_SYNC_EXECUTOR_RESTARTED'
                WHERE status = 'running'
                """,
                (now,),
            )
            await db.commit()
            return int(cursor.rowcount or 0)
