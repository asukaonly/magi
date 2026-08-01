"""SQLite-backed store for runtime execution traces."""

from __future__ import annotations

import asyncio
from dataclasses import fields
from pathlib import Path
import sqlite3
import time
from typing import Any, Awaitable, Callable, TypeVar

import aiosqlite

from ..core.logger import get_logger
from ..core.operation_barrier import AsyncOperationBarrier
from ..core.sqlite import sqlite_connection_async
from .contracts import PluginIngressClearStateReader
from .plugin_ingress import PluginIngressPersistenceMixin
from .runtime_notifications import RuntimeNotificationPersistenceMixin
from .trace_records import TraceRecordPersistenceMixin

T = TypeVar("T")

logger = get_logger(__name__)

_SQLITE_LOCK_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.05, 0.1, 0.2)


def _is_retryable_sqlite_lock(exc: Exception) -> bool:
    if not isinstance(exc, (sqlite3.OperationalError, aiosqlite.OperationalError)):
        return False
    error_text = str(exc).lower()
    return "database is locked" in error_text or "database table is locked" in error_text


class RuntimeTraceStore(
    RuntimeNotificationPersistenceMixin,
    PluginIngressPersistenceMixin,
    TraceRecordPersistenceMixin,
):
    """Persist runtime trace data in a dedicated SQLite database."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/runtime/runtime_trace.db",
        plugin_ingress_clear_state_reader: PluginIngressClearStateReader | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._plugin_ingress_clear_state_reader = plugin_ingress_clear_state_reader
        self._plugin_ingress_barrier = AsyncOperationBarrier()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.commit()
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False

    async def _execute_hot_write(
        self,
        *,
        operation: str,
        write: Callable[[aiosqlite.Connection], Awaitable[T]],
    ) -> T:
        total_attempts = len(_SQLITE_LOCK_RETRY_DELAYS_SECONDS) + 1
        for attempt_index in range(total_attempts):
            try:
                async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
                    result = await write(db)
                    await db.commit()
                    return result
            except Exception as exc:
                if not _is_retryable_sqlite_lock(exc) or attempt_index >= len(_SQLITE_LOCK_RETRY_DELAYS_SECONDS):
                    raise
                delay_seconds = _SQLITE_LOCK_RETRY_DELAYS_SECONDS[attempt_index]
                logger.warning(
                    "runtime_trace.hot_write_retry",
                    operation=operation,
                    attempt=attempt_index + 1,
                    max_attempts=total_attempts,
                    delay_ms=int(delay_seconds * 1000),
                    error=str(exc),
                )
                await asyncio.sleep(delay_seconds)
        raise RuntimeError(f"unreachable hot-write retry path for {operation}")

    async def _upsert_detail(self, sql: str, params: tuple[Any, ...]) -> None:
        await self._execute_hot_write(
            operation="upsert_detail",
            write=lambda db: db.execute(sql, params),
        )

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            return await cursor.fetchone()

    @staticmethod
    def _row_to_record(record_type: type[T], row: aiosqlite.Row | None) -> T | None:
        if row is None:
            return None
        values = {
            field.name: row[field.name]
            for field in fields(record_type)
            if field.name in row.keys()
        }
        return record_type(**values)

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
