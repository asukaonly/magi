"""SQLite persistence for background tasks.

The store owns the ``background_tasks`` and ``background_task_events`` tables
inside ``~/.magi/runtime/background_tasks.db``. It is IO-only: lifecycle
rules (which transitions are legal, semaphore accounting, retry semantics)
live in :mod:`magi.agent.background.manager`, which lands in phase 1.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from .contracts import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
)

logger = get_logger(__name__)


_DEFAULT_DB_PATH = "~/.magi/runtime/background_tasks.db"


class BackgroundTaskStore:
    """Persist and query background tasks plus their event logs."""

    def __init__(self, *, db_path: str = _DEFAULT_DB_PATH) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS background_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    origin_turn_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL DEFAULT 0,
                    spec_json TEXT NOT NULL,
                    orchestration_id TEXT,
                    user_task_id TEXT,
                    summary TEXT,
                    result_payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    cancel_reason TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bg_tasks_user_status
                    ON background_tasks(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_bg_tasks_session
                    ON background_tasks(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_bg_tasks_status_created
                    ON background_tasks(status, created_at);

                CREATE TABLE IF NOT EXISTS background_task_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES background_tasks(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_bg_events_task_created
                    ON background_task_events(task_id, created_at);
                """
            )
            await db.commit()
        self._initialized = True

    # ------------------------------------------------------------------
    # Task persistence
    # ------------------------------------------------------------------

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

    async def get_task(self, task_id: str) -> Optional[BackgroundTask]:
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
                "DELETE FROM background_task_events WHERE task_id = ?",
                (task_id,),
            )
            cursor = await db.execute(
                "DELETE FROM background_tasks WHERE task_id = ?",
                (task_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def list_tasks(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        statuses: Optional[list[BackgroundTaskStatus]] = None,
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
            f"SELECT * FROM background_tasks {where} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([int(limit), int(offset)])
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

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
        """Mark orphaned ``running``/``cancelling`` tasks as ``failed``.

        Called at backend startup. Any task that was live in-process before
        the previous shutdown is considered orphaned — there is no worker
        still holding its state. Returns the tasks that were transitioned so
        the caller can emit events.
        """
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
                await db.execute(
                    """
                    UPDATE background_tasks
                    SET status = ?, error = ?, finished_at = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        BackgroundTaskStatus.FAILED.value,
                        reason,
                        now,
                        now,
                        str(row["task_id"]),
                    ),
                )
                task = self._row_to_task(row)
                task.status = BackgroundTaskStatus.FAILED
                task.error = reason
                task.finished_at = now
                task.updated_at = now
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
        """Hard-delete terminal tasks older than ``retention_seconds``.

        Only tasks whose status is ``succeeded`` / ``failed`` / ``cancelled``
        are eligible — active rows are never removed. The cutoff compares
        against ``finished_at`` when present, otherwise ``updated_at`` to
        cover rows whose finish timestamp was not populated on a legacy
        path. The related ``background_task_events`` rows are deleted in
        the same transaction. Returns the number of tasks deleted.
        """
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

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    async def append_event(self, event: BackgroundTaskEvent) -> BackgroundTaskEvent:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                """
                INSERT INTO background_task_events (
                    event_id, task_id, attempt_index, event_type,
                    from_status, to_status, message, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    int(event.attempt_index),
                    event.event_type,
                    event.from_status.value if event.from_status is not None else None,
                    event.to_status.value if event.to_status is not None else None,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False),
                    float(event.created_at),
                ),
            )
            await db.commit()
        return event

    async def list_events(
        self,
        task_id: str,
        *,
        limit: int = 500,
    ) -> list[BackgroundTaskEvent]:
        """Return events for a task in insertion (creation) order."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM background_task_events
                WHERE task_id = ?
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (task_id, int(limit)),
            )
            rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> BackgroundTask:
        spec_data: dict[str, Any] = json.loads(str(row["spec_json"] or "{}"))
        # Defensive: spec_json is authoritative but we also keep the
        # denormalised columns in sync; prefer spec_json for round-trips
        # and fall back to the columns for legacy rows.
        spec_data.setdefault("user_id", str(row["user_id"]))
        spec_data.setdefault("session_id", str(row["session_id"]))
        spec_data.setdefault("origin_turn_id", str(row["origin_turn_id"]))
        spec_data.setdefault("title", str(row["title"]))
        spec_data.setdefault("goal", str(row["goal"]))
        spec = BackgroundTaskSpec.from_dict(spec_data)
        return BackgroundTask(
            task_id=str(row["task_id"]),
            spec=spec,
            status=BackgroundTaskStatus(str(row["status"])),
            attempt_index=int(row["attempt_index"] or 0),
            orchestration_id=(
                str(row["orchestration_id"])
                if row["orchestration_id"] is not None
                else None
            ),
            user_task_id=(
                str(row["user_task_id"])
                if row["user_task_id"] is not None
                else None
            ),
            summary=(
                str(row["summary"]) if row["summary"] is not None else None
            ),
            result_payload=json.loads(str(row["result_payload_json"] or "{}")),
            error=(str(row["error"]) if row["error"] is not None else None),
            cancel_reason=(
                str(row["cancel_reason"])
                if row["cancel_reason"] is not None
                else None
            ),
            created_at=float(row["created_at"]),
            started_at=(
                float(row["started_at"]) if row["started_at"] is not None else None
            ),
            finished_at=(
                float(row["finished_at"]) if row["finished_at"] is not None else None
            ),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _row_to_event(row: aiosqlite.Row) -> BackgroundTaskEvent:
        from_raw = row["from_status"]
        to_raw = row["to_status"]
        return BackgroundTaskEvent(
            event_id=str(row["event_id"]),
            task_id=str(row["task_id"]),
            attempt_index=int(row["attempt_index"] or 0),
            event_type=str(row["event_type"]),
            from_status=(
                BackgroundTaskStatus(str(from_raw)) if from_raw is not None else None
            ),
            to_status=(
                BackgroundTaskStatus(str(to_raw)) if to_raw is not None else None
            ),
            message=str(row["message"] or ""),
            payload=json.loads(str(row["payload_json"] or "{}")),
            created_at=float(row["created_at"]),
        )
