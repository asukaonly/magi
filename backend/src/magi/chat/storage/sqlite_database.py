"""SQLite driver for chat persistence transactions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import sqlite3

from ...core.sqlite import sqlite_connection_async, connect_sqlite
from .statements import ChatSql, render_sql


class SqliteAsyncChatConnection:
    """Expose SQLite's transaction semantics through the internal connection port."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    async def begin_write(self) -> None:
        if not self._connection.in_transaction:
            await self._connection.execute("BEGIN IMMEDIATE")

    async def execute(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> aiosqlite.Cursor:
        return await self._connection.execute(render_sql(sql, "sqlite"), parameters)

    async def executemany(self, sql: str | ChatSql, parameters: Iterable[Sequence[object]]) -> aiosqlite.Cursor:
        return await self._connection.executemany(render_sql(sql, "sqlite"), parameters)

    async def execute_fetchall(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> Sequence[aiosqlite.Row]:
        return await self._connection.execute_fetchall(render_sql(sql, "sqlite"), parameters)

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


class SqliteChatReadConnection:
    """Own local snapshot, secure deletion, and file reclamation semantics."""

    def __init__(self, path: Path) -> None:
        self._connection = connect_sqlite(path, profile="mixed")

    def execute(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        return self._connection.execute(render_sql(sql, "sqlite"), parameters)

    def executemany(self, sql: str | ChatSql, parameters: Iterable[Sequence[object]]) -> sqlite3.Cursor:
        return self._connection.executemany(render_sql(sql, "sqlite"), parameters)

    def begin_read(self) -> None:
        self._connection.execute("BEGIN")

    def begin_write(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")

    def prepare_content_clear(self) -> None:
        self._connection.execute("PRAGMA secure_delete=ON")

    def compact_cleared_content(self) -> None:
        self._connection.execute("VACUUM")

    def checkpoint_cleared_content(self) -> None:
        checkpoint = self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and int(checkpoint[0] or 0) != 0:
            raise RuntimeError("Global chat clear could not truncate the WAL")

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


class SqliteChatReadDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def is_present(self) -> bool:
        return self.path.exists()

    def open(self) -> SqliteChatReadConnection:
        return SqliteChatReadConnection(self.path)
