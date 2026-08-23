"""Background task row persistence and queries."""

from __future__ import annotations

import json
import time

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import secure_compact_sqlite, sqlite_connection_async
from .contracts import BackgroundTask, BackgroundTaskEvent, BackgroundTaskStatus

logger = get_logger(__name__)


class BackgroundTaskRowStoreMixin:
    """Persist, query, recover, and purge background task rows."""

    db_path: str

    async def create_task(self, task: BackgroundTask) -> BackgroundTask:
        """Insert a brand-new task row. Fails loudly if ``task_id`` exists."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                """
                INSERT INTO background_tasks (
                    task_id, user_id, session_id, origin_turn_id,
                    title, goal, status, attempt_index, spec_json,
                    orchestration_id, user_task_id, summary, result_payload_json,
                    error, cancel_reason, created_at, started_at, finished_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.spec.user_id,
                    task.spec.session_id,
                    task.spec.origin_turn_id,
                    task.spec.title,
                    task.spec.goal,
                    task.status.value,
                    int(task.attempt_index),
                    json.dumps(task.spec.to_dict(), ensure_ascii=False),
                    task.orchestration_id,
                    task.user_task_id,
                    task.summary,
                    json.dumps(task.result_payload, ensure_ascii=False),
                    task.error,
                    task.cancel_reason,
                    float(task.created_at),
                    (float(task.started_at) if task.started_at is not None else None),
                    (float(task.finished_at) if task.finished_at is not None else None),
                    float(task.updated_at),
                ),
            )
            await db.commit()
        return task

    async def update_task(self, task: BackgroundTask) -> BackgroundTask:
        """Overwrite the mutable columns for an existing task row."""
        await self.initialize()
        task.updated_at = time.time()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                """
                UPDATE background_tasks SET
                    status = ?,
                    attempt_index = ?,
                    orchestration_id = ?,
                    user_task_id = ?,
                    summary = ?,
                    result_payload_json = ?,
                    error = ?,
                    cancel_reason = ?,
                    started_at = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    task.status.value,
                    int(task.attempt_index),
                    task.orchestration_id,
                    task.user_task_id,
                    task.summary,
                    json.dumps(task.result_payload, ensure_ascii=False),
                    task.error,
                    task.cancel_reason,
                    (float(task.started_at) if task.started_at is not None else None),
                    (float(task.finished_at) if task.finished_at is not None else None),
                    float(task.updated_at),
                    task.task_id,
                ),
            )
            await db.commit()
        return task

    async def get_task(self, task_id: str) -> BackgroundTask | None:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM background_tasks WHERE task_id = ?", (task_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    async def delete_task(self, task_id: str) -> bool:
        """Hard-delete a task and its event log. Used for admin dismiss."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                "DELETE FROM tool_effect_attempts WHERE task_id = ?",
                (task_id,),
            )
            await db.execute(
                "DELETE FROM background_task_completion_intents WHERE task_id = ?",
                (task_id,),
            )
            await db.execute(
                "DELETE FROM background_task_events WHERE task_id = ?",
                (task_id,),
            )
            cursor = await db.execute(
                "DELETE FROM background_tasks WHERE task_id = ?",
                (task_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def clear_all(self) -> dict[str, int]:
        """Atomically remove all task rows, events, and completion intents."""
        await self.initialize()
        tables = (
            "tool_effect_attempts",
            "background_task_completion_intents",
            "background_task_events",
            "background_tasks",
        )
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                removed: dict[str, int] = {}
                for table in tables:
                    cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
                    row = await cursor.fetchone()
                    removed[table] = int(row[0]) if row is not None else 0
                for table in tables:
                    await db.execute(f"DELETE FROM {table}")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        await secure_compact_sqlite(self.db_path, profile="hot_write")
        return removed

    async def list_tasks(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        statuses: list[BackgroundTaskStatus] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BackgroundTask]:
        await self.initialize()
        conditions: list[str] = []
        params: list[object] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if statuses:
            placeholders = ",".join(["?"] * len(statuses))
            conditions.append(f"status IN ({placeholders})")
            params.extend(status.value for status in statuses)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            f"SELECT * FROM background_tasks {where} " "ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([int(limit), int(offset)])
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def count_tasks(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        statuses: list[BackgroundTaskStatus] | None = None,
    ) -> int:
        await self.initialize()
        conditions: list[str] = []
        params: list[object] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if statuses:
            placeholders = ",".join(["?"] * len(statuses))
            conditions.append(f"status IN ({placeholders})")
            params.extend(status.value for status in statuses)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT COUNT(*) FROM background_tasks {where}"
        async with sqlite_connection_async(self.db_path, profile="readonly") as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def list_pending(self, *, limit: int = 200) -> list[BackgroundTask]:
        """Queue order: oldest pending first (FIFO within priority)."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM background_tasks
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (BackgroundTaskStatus.PENDING.value, int(limit)),
            )
            rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def recover_stale_running(
        self, *, reason: str = "backend_restart"
    ) -> list[BackgroundTask]:
        """Mark orphaned ``running``/``cancelling`` tasks as ``failed``."""
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM background_tasks
                WHERE status IN (?, ?)
                """,
                (
                    BackgroundTaskStatus.RUNNING.value,
                    BackgroundTaskStatus.CANCELLING.value,
                ),
            )
            rows = await cursor.fetchall()
            recovered: list[BackgroundTask] = []
            for row in rows:
                task = self._row_to_task(row)
                previous = task.status
                task.status = BackgroundTaskStatus.FAILED
                task.error = reason
                task.finished_at = now
                task.updated_at = now
                await self._update_task_row(db, task)
                await self._insert_event_row(
                    db,
                    BackgroundTaskEvent.transition(
                        task_id=task.task_id,
                        attempt_index=task.attempt_index,
                        from_status=previous,
                        to_status=BackgroundTaskStatus.FAILED,
                        message=reason,
                    ),
                )
                await self._insert_completion_intent_row(db, task)
                recovered.append(task)
            await db.commit()
        if recovered:
            logger.info(
                "Recovered stale background tasks on startup",
                count=len(recovered),
                reason=reason,
            )
        return recovered

    async def purge_expired(
        self,
        *,
        retention_seconds: float,
        now: float | None = None,
    ) -> int:
        """Hard-delete terminal tasks older than ``retention_seconds``."""
        if retention_seconds <= 0:
            return 0
        await self.initialize()
        cutoff = (now if now is not None else time.time()) - retention_seconds
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                """
                SELECT task_id FROM background_tasks
                WHERE status IN (?, ?, ?)
                  AND COALESCE(finished_at, updated_at) < ?
                """,
                (
                    BackgroundTaskStatus.SUCCEEDED.value,
                    BackgroundTaskStatus.FAILED.value,
                    BackgroundTaskStatus.CANCELLED.value,
                    cutoff,
                ),
            )
            rows = await cursor.fetchall()
            task_ids = [str(row[0]) for row in rows]
            if not task_ids:
                return 0
            placeholders = ",".join("?" * len(task_ids))
            await db.execute(
                f"DELETE FROM background_task_events WHERE task_id IN ({placeholders})",
                task_ids,
            )
            await db.execute(
                "DELETE FROM background_task_completion_intents "
                f"WHERE task_id IN ({placeholders})",
                task_ids,
            )
            await db.execute(
                f"DELETE FROM tool_effect_attempts WHERE task_id IN ({placeholders})",
                task_ids,
            )
            await db.execute(
                f"DELETE FROM background_tasks WHERE task_id IN ({placeholders})",
                task_ids,
            )
            await db.commit()
        logger.info(
            "Purged expired background tasks",
            count=len(task_ids),
            retention_seconds=retention_seconds,
        )
        return len(task_ids)


__all__ = ["BackgroundTaskRowStoreMixin"]
