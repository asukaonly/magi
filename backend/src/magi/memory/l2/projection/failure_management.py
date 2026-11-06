"""User-owned disposition and paginated diagnostics for terminal jobs."""

from __future__ import annotations

import time
from typing import Any, Literal

import aiosqlite

from magi.core.sqlite import sqlite_connection_async

from .diagnostics import projection_failure_reason, projection_retry_allowed
from .governance import active_projection_event_predicate


class ProjectionFailureManagementMixin:
    db_path: str

    async def list_failure_records(
        self, *, status: Literal["failed", "ignored"] = "failed",
        source: str | None = None, reason: str | None = None,
        event_id: str | None = None, limit: int = 20, offset: int = 0,
    ) -> dict[str, Any]:
        """Apply status and cause filters before counting and pagination."""
        if status not in {"failed", "ignored"} or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid failure record query")
        predicates = ["jobs.status = ?", active_projection_event_predicate("jobs.event_id")]
        params: list[str | int] = [status]
        for field, value in (("source", source), ("event_id", event_id)):
            if value is not None:
                predicates.append(f"jobs.{field} = ?")
                params.append(value)
        if reason is not None:
            predicates.append("projection_failure_reason(jobs.last_error) = ?")
            params.append(reason)
        where = " AND ".join(predicates)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.create_function("projection_failure_reason", 1, projection_failure_reason, deterministic=True)
            await db.execute("BEGIN")
            cursor = await db.execute(f"SELECT COUNT(*) FROM l2_projection_jobs AS jobs WHERE {where}", params)
            total = int((await cursor.fetchone())[0])
            cursor = await db.execute(
                f"""SELECT event_id, source, status, attempt_count, last_error,
                    COALESCE(terminal_at, updated_at) AS last_failed_at, updated_at
                    FROM l2_projection_jobs AS jobs WHERE {where}
                    ORDER BY updated_at DESC, event_id LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            )
            rows = await cursor.fetchall()
            await db.commit()
        return {
            "items": [{
                "event_id": str(row["event_id"]), "source": str(row["source"]),
                "status": str(row["status"]), "attempt_count": int(row["attempt_count"]),
                "reason": projection_failure_reason(row["last_error"]),
                "retry_allowed": projection_retry_allowed(row["last_error"]),
                "error": row["last_error"], "last_failed_at": float(row["last_failed_at"]),
                "updated_at": float(row["updated_at"]),
            } for row in rows],
            "total": total, "limit": limit, "offset": offset,
        }

    async def set_failure_disposition(
        self, *, action: Literal["ignore", "restore"], selections: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Change only the exact terminal snapshots the user reviewed."""
        if action not in {"ignore", "restore"} or not 1 <= len(selections) <= 100:
            raise ValueError("Invalid failure disposition request")
        expected, target = ("failed", "ignored") if action == "ignore" else ("ignored", "failed")
        changed = 0
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for selection in selections:
                    cursor = await db.execute(
                        f"""UPDATE l2_projection_jobs SET status = ?,
                            terminal_at = COALESCE(terminal_at, updated_at), updated_at = ?
                            WHERE event_id = ? AND status = ? AND updated_at = ?
                              AND {active_projection_event_predicate('l2_projection_jobs.event_id')}""",
                        (target, time.time(), selection["event_id"], expected, selection["expected_updated_at"]),
                    )
                    changed += max(0, int(cursor.rowcount))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return {"changed_count": changed, "unchanged_count": len(selections) - changed}
