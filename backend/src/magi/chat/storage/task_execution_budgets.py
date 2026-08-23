"""Durable task-execution budgets keyed by the accepted root chat turn."""

from __future__ import annotations

import time

import aiosqlite

from ...core.sqlite import sqlite_connection_async

_RESOURCE_COLUMNS = {
    "llm_calls": ("llm_calls_used", "max_llm_calls"),
    "worker_launches": ("worker_launches_used", "max_worker_launches"),
}


class ChatTaskExecutionBudgetPersistenceMixin:
    """Atomically reserve execution capacity across processes and retries."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def ensure_task_execution_budget(
        self,
        *,
        root_turn_id: str,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> tuple[int, int, int, int]:
        """Create a root budget once, then return its authoritative counters."""
        self._validate_identity_and_limits(
            root_turn_id=root_turn_id,
            max_llm_calls=max_llm_calls,
            max_worker_launches=max_worker_launches,
        )
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._ensure_task_execution_budget_row(
                    db,
                    root_turn_id=root_turn_id,
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
        """Reserve a positive count without allowing concurrent oversubscription."""
        self._validate_identity_and_limits(
            root_turn_id=root_turn_id,
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
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._ensure_task_execution_budget_row(
                    db,
                    root_turn_id=root_turn_id,
                    max_llm_calls=max_llm_calls,
                    max_worker_launches=max_worker_launches,
                )
                accepted = int(row[used_column]) + count <= int(row[limit_column])
                if accepted:
                    await db.execute(
                        f"""
                        UPDATE chat_task_execution_budgets
                        SET {used_column} = {used_column} + ?
                        WHERE root_turn_id = ?
                        """,
                        (count, root_turn_id),
                    )
                    updated_row = await self._fetch_budget_row(db, root_turn_id)
                    if updated_row is None:
                        raise RuntimeError("Task execution budget row disappeared")
                    row = updated_row
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
        """Release unused prepaid LLM capacity from the durable counter."""
        if not str(root_turn_id or "").strip():
            raise ValueError("Task budget root_turn_id is required")
        if count < 1:
            raise ValueError("Task budget releases must be positive")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._fetch_budget_row(db, root_turn_id)
                if row is None:
                    # The owning turn may be deleted while an admitted branch
                    # is unwinding. Its FK-owned projection is already gone,
                    # so release is idempotently complete.
                    await db.commit()
                    return None
                if count > int(row["llm_calls_used"]):
                    raise ValueError("Cannot release more LLM calls than are reserved")
                await db.execute(
                    """
                    UPDATE chat_task_execution_budgets
                    SET llm_calls_used = llm_calls_used - ?
                    WHERE root_turn_id = ?
                    """,
                    (count, root_turn_id),
                )
                updated_row = await self._fetch_budget_row(db, root_turn_id)
                if updated_row is None:
                    raise RuntimeError("Task execution budget row disappeared")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return self._budget_state(updated_row)

    async def _ensure_task_execution_budget_row(
        self,
        db: aiosqlite.Connection,
        *,
        root_turn_id: str,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> aiosqlite.Row:
        await db.execute(
            """
            INSERT INTO chat_task_execution_budgets(
                root_turn_id,
                max_llm_calls,
                llm_calls_used,
                max_worker_launches,
                worker_launches_used,
                created_at_ms
            )
            SELECT ?, ?, 0, ?, 0, ?
            WHERE EXISTS (
                SELECT 1 FROM chat_turns WHERE turn_id = ?
            )
            ON CONFLICT(root_turn_id) DO NOTHING
            """,
            (
                root_turn_id,
                max_llm_calls,
                max_worker_launches,
                int(time.time() * 1000),
                root_turn_id,
            ),
        )
        row = await self._fetch_budget_row(db, root_turn_id)
        if row is None:
            raise ValueError(f"Task budget root turn does not exist: {root_turn_id}")
        return row

    @staticmethod
    async def _fetch_budget_row(
        db: aiosqlite.Connection,
        root_turn_id: str,
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            """
            SELECT
                max_llm_calls,
                llm_calls_used,
                max_worker_launches,
                worker_launches_used
            FROM chat_task_execution_budgets
            WHERE root_turn_id = ?
            """,
            (root_turn_id,),
        )
        return await cursor.fetchone()

    @staticmethod
    def _budget_state(row: aiosqlite.Row | None) -> tuple[int, int, int, int]:
        if row is None:
            raise RuntimeError("Task execution budget row disappeared")
        return (
            int(row["max_llm_calls"]),
            int(row["llm_calls_used"]),
            int(row["max_worker_launches"]),
            int(row["worker_launches_used"]),
        )

    @staticmethod
    def _validate_identity_and_limits(
        *,
        root_turn_id: str,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> None:
        if not str(root_turn_id or "").strip():
            raise ValueError("Task budget root_turn_id is required")
        if max_llm_calls < 1 or max_worker_launches < 1:
            raise ValueError("Task budget limits must be positive")


__all__ = ["ChatTaskExecutionBudgetPersistenceMixin"]
