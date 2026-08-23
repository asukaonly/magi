"""Durable execution budgets for standalone background tasks."""

from __future__ import annotations

import aiosqlite

from ...core.sqlite import sqlite_connection_async

_RESOURCE_COLUMNS = {
    "llm_calls": ("task_llm_calls_used", "task_max_llm_calls"),
    "worker_launches": ("task_worker_launches_used", "task_max_worker_launches"),
}


class BackgroundTaskBudgetStoreMixin:
    """Implement TaskExecutionBudgetStore using the stable background task id."""

    db_path: str

    async def ensure_task_execution_budget(
        self,
        *,
        root_turn_id: str,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> tuple[int, int, int, int]:
        task_id = self._validate_budget_request(
            task_id=root_turn_id,
            max_llm_calls=max_llm_calls,
            max_worker_launches=max_worker_launches,
        )
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._ensure_budget_row(
                    db,
                    task_id=task_id,
                    max_llm_calls=max_llm_calls,
                    max_worker_launches=max_worker_launches,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return self._budget_state(row)

    async def reserve_task_execution_budget(
        self,
        *,
        root_turn_id: str,
        resource: str,
        count: int,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> tuple[bool, int, int, int, int]:
        task_id = self._validate_budget_request(
            task_id=root_turn_id,
            max_llm_calls=max_llm_calls,
            max_worker_launches=max_worker_launches,
        )
        if count < 1:
            raise ValueError("Task budget reservations must be positive")
        columns = _RESOURCE_COLUMNS.get(resource)
        if columns is None:
            raise ValueError(f"Unknown task budget resource: {resource}")
        used_column, limit_column = columns

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._ensure_budget_row(
                    db,
                    task_id=task_id,
                    max_llm_calls=max_llm_calls,
                    max_worker_launches=max_worker_launches,
                )
                accepted = int(row[used_column]) + count <= int(row[limit_column])
                if accepted:
                    await db.execute(
                        f"""
                        UPDATE background_tasks
                        SET {used_column} = {used_column} + ?
                        WHERE task_id = ?
                        """,
                        (count, task_id),
                    )
                    updated = await self._fetch_budget_row(db, task_id)
                    if updated is None:
                        raise RuntimeError("Background task budget row disappeared")
                    row = updated
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return (accepted, *self._budget_state(row))

    async def release_task_execution_llm_calls(
        self,
        *,
        root_turn_id: str,
        count: int,
    ) -> tuple[int, int, int, int] | None:
        task_id = str(root_turn_id or "").strip()
        if not task_id:
            raise ValueError("Background task budget identity is required")
        if count < 1:
            raise ValueError("Task budget releases must be positive")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._fetch_budget_row(db, task_id)
                if row is None:
                    await db.commit()
                    return None
                if count > int(row["task_llm_calls_used"]):
                    raise ValueError("Cannot release more LLM calls than are reserved")
                await db.execute(
                    """
                    UPDATE background_tasks
                    SET task_llm_calls_used = task_llm_calls_used - ?
                    WHERE task_id = ?
                    """,
                    (count, task_id),
                )
                updated = await self._fetch_budget_row(db, task_id)
                if updated is None:
                    raise RuntimeError("Background task budget row disappeared")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return self._budget_state(updated)

    @staticmethod
    def _validate_budget_request(
        *,
        task_id: str,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> str:
        normalized = str(task_id or "").strip()
        if not normalized:
            raise ValueError("Background task budget identity is required")
        if max_llm_calls < 1 or max_worker_launches < 1:
            raise ValueError("Task budget limits must be positive")
        return normalized

    @staticmethod
    async def _ensure_budget_row(
        db: aiosqlite.Connection,
        *,
        task_id: str,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> aiosqlite.Row:
        await db.execute(
            """
            UPDATE background_tasks
            SET task_max_llm_calls = COALESCE(task_max_llm_calls, ?),
                task_max_worker_launches = COALESCE(task_max_worker_launches, ?)
            WHERE task_id = ?
            """,
            (max_llm_calls, max_worker_launches, task_id),
        )
        row = await BackgroundTaskBudgetStoreMixin._fetch_budget_row(db, task_id)
        if row is None:
            raise ValueError(f"Background task does not exist: {task_id}")
        return row

    @staticmethod
    async def _fetch_budget_row(
        db: aiosqlite.Connection,
        task_id: str,
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            """
            SELECT
                task_max_llm_calls,
                task_llm_calls_used,
                task_max_worker_launches,
                task_worker_launches_used
            FROM background_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        )
        return await cursor.fetchone()

    @staticmethod
    def _budget_state(row: aiosqlite.Row) -> tuple[int, int, int, int]:
        return (
            int(row["task_max_llm_calls"]),
            int(row["task_llm_calls_used"]),
            int(row["task_max_worker_launches"]),
            int(row["task_worker_launches_used"]),
        )


__all__ = ["BackgroundTaskBudgetStoreMixin"]
