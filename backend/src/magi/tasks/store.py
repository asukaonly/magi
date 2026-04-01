"""SQLite-backed persistence for user tasks."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .models import TaskPriority, TaskStatus, UserTask


class TaskStore:
    """Persist and query user tasks in a dedicated SQLite database."""

    def __init__(self, *, db_path: str = "~/.magi/runtime/tasks.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    due_date REAL,
                    created_by TEXT NOT NULL DEFAULT 'user',
                    user_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT,
                    linked_orchestration_id TEXT,
                    linked_turn_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_user_status
                    ON tasks(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_tasks_user_updated
                    ON tasks(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_linked_orch
                    ON tasks(linked_orchestration_id)
                    WHERE linked_orchestration_id IS NOT NULL;
                """
            )
        self._initialized = True

    async def create_task(self, task: UserTask) -> UserTask:
        """Insert a new task. Assigns task_id and timestamps if empty."""
        await self.initialize()
        now = time.time()
        if not task.task_id:
            task.task_id = f"task_{uuid.uuid4().hex[:12]}"
        if task.created_at <= 0:
            task.created_at = now
        task.updated_at = now
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                """
                INSERT INTO tasks (
                    task_id, title, description, status, priority,
                    tags_json, due_date, created_by, user_id, session_id,
                    linked_orchestration_id, linked_turn_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.title,
                    task.description,
                    task.status.value,
                    task.priority.value,
                    json.dumps(task.tags, ensure_ascii=False),
                    task.due_date,
                    task.created_by,
                    task.user_id,
                    task.session_id,
                    task.linked_orchestration_id,
                    task.linked_turn_id,
                    task.created_at,
                    task.updated_at,
                ),
            )
            await db.commit()
        return task

    async def get_task(self, task_id: str) -> Optional[UserTask]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    async def list_tasks(
        self,
        *,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[UserTask]:
        await self.initialize()
        conditions = ["user_id = ?"]
        params: list[object] = [user_id]
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions)
        query = f"SELECT * FROM tasks WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def update_task(
        self,
        task_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
        due_date: Optional[float] = ...,  # type: ignore[assignment]
        linked_orchestration_id: Optional[str] = ...,  # type: ignore[assignment]
        linked_turn_id: Optional[str] = ...,  # type: ignore[assignment]
    ) -> Optional[UserTask]:
        """Update specified fields on a task. Only non-sentinel values are applied."""
        await self.initialize()
        sets: list[str] = []
        params: list[object] = []
        _SENTINEL = ...
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if description is not None:
            sets.append("description = ?")
            params.append(description)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if priority is not None:
            sets.append("priority = ?")
            params.append(priority)
        if tags is not None:
            sets.append("tags_json = ?")
            params.append(json.dumps(tags, ensure_ascii=False))
        if due_date is not _SENTINEL:
            sets.append("due_date = ?")
            params.append(due_date)
        if linked_orchestration_id is not _SENTINEL:
            sets.append("linked_orchestration_id = ?")
            params.append(linked_orchestration_id)
        if linked_turn_id is not _SENTINEL:
            sets.append("linked_turn_id = ?")
            params.append(linked_turn_id)
        if not sets:
            return await self.get_task(task_id)
        now = time.time()
        sets.append("updated_at = ?")
        params.append(now)
        params.append(task_id)
        query = f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?"
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(query, params)
            await db.commit()
        return await self.get_task(task_id)

    async def delete_task(self, task_id: str) -> bool:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def list_by_orchestration(self, orchestration_id: str) -> list[UserTask]:
        """Return tasks linked to a specific orchestration context."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE linked_orchestration_id = ? ORDER BY created_at ASC",
                (orchestration_id,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> UserTask:
        return UserTask(
            task_id=str(row["task_id"]),
            title=str(row["title"]),
            description=str(row["description"] or ""),
            status=TaskStatus(str(row["status"])),
            priority=TaskPriority(str(row["priority"])),
            tags=json.loads(str(row["tags_json"] or "[]")),
            due_date=float(row["due_date"]) if row["due_date"] is not None else None,
            created_by=str(row["created_by"]),
            user_id=str(row["user_id"]),
            session_id=str(row["session_id"]) if row["session_id"] is not None else None,
            linked_orchestration_id=(
                str(row["linked_orchestration_id"]) if row["linked_orchestration_id"] is not None else None
            ),
            linked_turn_id=str(row["linked_turn_id"]) if row["linked_turn_id"] is not None else None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
