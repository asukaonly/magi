"""SQLite driver for chat persistence transactions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import cast

import aiosqlite
import sqlite3

from ...core.sqlite import sqlite_connection_async, connect_sqlite
from ...core.persistence_errors import PersistenceConflictError, PersistenceUnavailableError
from .statements import ChatSql, render_sql


@contextmanager
def storage_errors() -> Iterator[None]:
    """Keep driver exceptions and raw query details inside the SQLite adapter."""
    try:
        yield
    except sqlite3.IntegrityError as exc:
        raise PersistenceConflictError("Chat storage constraint rejected the write") from exc
    except sqlite3.Error as exc:
        raise PersistenceUnavailableError("Chat storage operation could not be confirmed") from exc


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
        return cast(Sequence[sqlite3.Row], await self._connection.execute_fetchall(render_sql(sql, "sqlite"), parameters))

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
        with storage_errors():
            async with sqlite_connection_async(self.path, profile="mixed") as connection:
                yield SqliteAsyncChatConnection(connection)


class SqliteChatReadCursor:
    """Normalize failures raised while fetching a lazily evaluated SQLite row."""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor
        self.rowcount = cursor.rowcount

    @storage_errors()
    def fetchone(self) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self._cursor.fetchone())

    @storage_errors()
    def fetchall(self) -> list[sqlite3.Row]:
        return self._cursor.fetchall()


class SqliteChatReadConnection:
    """Own local snapshot, secure deletion, and file reclamation semantics."""

    @storage_errors()
    def __init__(self, path: Path) -> None:
        self._connection = connect_sqlite(path, profile="mixed")

    @storage_errors()
    def execute(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> SqliteChatReadCursor:
        return SqliteChatReadCursor(self._connection.execute(render_sql(sql, "sqlite"), parameters))

    @storage_errors()
    def executemany(self, sql: str | ChatSql, parameters: Iterable[Sequence[object]]) -> SqliteChatReadCursor:
        return SqliteChatReadCursor(self._connection.executemany(render_sql(sql, "sqlite"), parameters))

    @storage_errors()
    def begin_read(self) -> None:
        self._connection.execute("BEGIN")

    @storage_errors()
    def begin_write(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")

    @storage_errors()
    def prepare_content_clear(self) -> None:
        self._connection.execute("PRAGMA secure_delete=ON")

    @storage_errors()
    def compact_cleared_content(self) -> None:
        self._connection.execute("VACUUM")

    @storage_errors()
    def checkpoint_cleared_content(self) -> None:
        checkpoint = self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and int(checkpoint[0] or 0) != 0:
            raise RuntimeError("Global chat clear could not truncate the WAL")

    @storage_errors()
    def commit(self) -> None:
        self._connection.commit()

    @storage_errors()
    def rollback(self) -> None:
        self._connection.rollback()

    @storage_errors()
    def close(self) -> None:
        self._connection.close()


class SqliteChatReadDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def is_present(self) -> bool:
        return self.path.exists()

    def open(self) -> SqliteChatReadConnection:
        return SqliteChatReadConnection(self.path)
