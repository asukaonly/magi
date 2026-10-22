"""SQLite driver for chat persistence transactions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from ...core.sqlite import sqlite_connection_async


class SqliteAsyncChatConnection:
    """Expose SQLite's transaction semantics through the internal connection port."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    async def begin_write(self) -> None:
        await self._connection.execute("BEGIN IMMEDIATE")

    async def execute(self, sql: str, parameters: Sequence[object] = ()) -> aiosqlite.Cursor:
        return await self._connection.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Iterable[Sequence[object]]) -> aiosqlite.Cursor:
        return await self._connection.executemany(sql, parameters)

    async def execute_fetchall(self, sql: str, parameters: Sequence[object] = ()) -> Sequence[aiosqlite.Row]:
        return await self._connection.execute_fetchall(sql, parameters)

    async def commit(self) -> None:
        await self._connection.commit()

    async def rollback(self) -> None:
        await self._connection.rollback()


class SqliteChatDatabase:
    """Provide independent async connections to one migrated local chat store."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.session() as connection:
            await connection.commit()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[SqliteAsyncChatConnection]:
        async with sqlite_connection_async(self.path, profile="mixed") as connection:
            yield SqliteAsyncChatConnection(connection)
