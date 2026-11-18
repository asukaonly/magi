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

    async def list_activity_page(
        self, *, since: float | None, until: float | None, target_types: list[str],
        statuses: list[str], limit: int, offset: int,
    ) -> dict[str, object]:
        """Read one row per execution, including the current state of pending sync jobs."""
        base = """
            WITH activity AS (
                SELECT e.*, j.job_id, j.created_at AS planned_at, j.started_at AS job_started_at,
                       CASE WHEN j.job_id IS NOT NULL THEN j.status
                            WHEN e.status = 'success' THEN 'succeeded' ELSE e.status END AS display_status
                FROM schedule_executions e
                LEFT JOIN source_sync_jobs j ON j.target_type = e.target_type AND j.target_key = e.target_key
                    AND j.status IN ('queued', 'running') AND j.execution_id = e.execution_id
                WHERE e.status = 'running'
                   OR ((:since IS NULL OR e.started_at >= :since) AND (:until IS NULL OR e.started_at <= :until))
            )
        """
        params = {"since": since, "until": until, "limit": limit, "offset": offset}
        filters = []
        for column, values in (("target_type", target_types), ("display_status", statuses)):
            if values:
                params[column] = json.dumps(values)
                filters.append(f"{column} IN (SELECT value FROM json_each(:{column}))")
        where = " WHERE " + " AND ".join(filters) if filters else ""
        async with self._connect() as db:
            await db.execute("BEGIN")
            counts = await db.execute_fetchall(
                base + "SELECT target_type, display_status, count(*) FROM activity GROUP BY 1, 2", params,
            )
            rows = await db.execute_fetchall(
                base + "SELECT * FROM activity" + where +
                " ORDER BY display_status IN ('running','queued') DESC, started_at DESC, execution_id DESC"
                " LIMIT :limit OFFSET :offset", params,
            )

        totals_by_type: dict[str, int] = {}
        totals_by_status: dict[str, int] = {}
        total = 0
        for target_type, status, count in counts:
            totals_by_type[target_type] = totals_by_type.get(target_type, 0) + count
            totals_by_status[status] = totals_by_status.get(status, 0) + count
            if (not target_types or target_type in target_types) and (not statuses or status in statuses):
                total += count

        activities = []
        for row in rows:
            job_id = row["job_id"]
            queued = bool(job_id) and row["display_status"] == "queued"
            stats = json.loads(row["stats_json"])
            activities.append({
                "activity_id": f"source_job:{job_id}" if job_id else f"execution:{row['execution_id']}",
                "schedule_id": row["schedule_id"], "target_type": row["target_type"], "target_key": row["target_key"],
                "status": row["display_status"], "manual": bool(row["manual"]),
                "planned_at": row["planned_at"] if job_id else row["started_at"],
                "started_at": row["job_started_at"] if job_id else row["started_at"],
                "finished_at": row["finished_at"], "duration_ms": row["duration_ms"],
                "result_message": row["result_message"], "error": row["error"], "stats": stats,
                "background_task_id": stats.get("background_task_id"), "cancellable": queued,
                "cancel_kind": "source_sync_job" if queued else None,
            })
        return {"activities": activities, "total": total, "target_type_counts": totals_by_type,
                "status_counts": totals_by_status}

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
