"""Execution record persistence operations for scheduler repository."""

from __future__ import annotations

import json
import uuid
from typing import Optional

from .contracts import ScheduledExecutionResult, ScheduledTargetType


class SchedulerExecutionRepositoryMixin:
    """Persist scheduler execution records and completion details."""

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

    async def complete_execution_result(
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
                SET status = ?,
                    error = ?,
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
                    "success" if result.success else "failed",
                    None if result.success else str(result.stats.get("error") or result.message or "Scheduled execution failed"),
                    finished_at,
                    max(0.0, (finished_at - started_at) * 1000.0),
                    result.message,
                    json.dumps(result.stats, ensure_ascii=False),
                    result.next_cursor if result.success else None,
                    result.watermark_ts if result.success else None,
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
            results.append(
                {
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
                }
            )
        return results


__all__ = ["SchedulerExecutionRepositoryMixin"]
