"""Native MySQL execution for shared chat transaction workflows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import Row
from typing import Any
from .schema import CHAT_TABLES

from ....core.persistence_errors import PersistenceConflictError
from ....core.async_cleanup import finish_cleanup
from ....db.mysql import MysqlDatabase
from ..statements import ChatSql, render_sql


class MysqlChatRow:
    """Expose driver-independent named and positional result access."""

    def __init__(self, row: Row[Any]) -> None:
        self._mapping = {key: value for key, value in row._mapping.items() if not key.startswith("__")}
        self._values = tuple(self._mapping.values())

    def keys(self) -> list[str]:
        return list(self._mapping)

    def __getitem__(self, key: str | int) -> Any:
        return self._values[key] if isinstance(key, int) else self._mapping[key]


class MysqlChatCursor:
    def __init__(self, result: CursorResult[Any]) -> None:
        self.rowcount = result.rowcount
        self._rows = [MysqlChatRow(row) for row in result] if result.returns_rows else []
        self._position = 0

    async def fetchone(self) -> MysqlChatRow | None:
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    async def fetchall(self) -> list[MysqlChatRow]:
        rows = self._rows[self._position:]
        self._position = len(self._rows)
        return rows


def bind_parameters(statement: str, count: int) -> str:
    """Adapt positional parameter markers without changing native SQL semantics."""
    output: list[str] = []
    quote: str | None = None
    found = 0
    for character in statement:
        if quote:
            if character == quote:
                quote = None
        elif character in "'\"`":
            quote = character
        elif character == "?":
            output.append("%s")
            found += 1
            continue
        output.append("%%" if character == "%" else character)
    if found != count:
        raise ValueError("Chat statement parameter count does not match its bindings")
    return "".join(output)


class MysqlAsyncChatConnection:
    """Hold the center row lock for each atomic chat operation."""

    def __init__(self, connection: AsyncConnection, center_id: str) -> None:
        self.connection = connection
        self.center_id = center_id
        self._locked = False

    async def begin_write(self) -> None:
        if self._locked and self.connection.in_transaction():
            return
        owner = (await self.connection.execute(text(
            "SELECT center_id FROM magi_chat_owner WHERE slot=1 FOR UPDATE"
        ))).scalar_one_or_none()
        if owner != self.center_id:
            raise PersistenceConflictError("Chat storage belongs to another center")
        self._locked = True

    async def execute(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> MysqlChatCursor:
        await self.begin_write()
        native = render_sql(sql, "mysql")
        try:
            result = await self.connection.exec_driver_sql(bind_parameters(native, len(parameters)), tuple(parameters))
        except DBAPIError as exc:
            if getattr(exc.orig, "args", (None,))[0] in {1644, 3819}:
                raise PersistenceConflictError("Chat write crossed a storage guard") from exc
            raise
        if native.lstrip().upper().startswith("INSERT IGNORE"):
            warnings = (await self.connection.exec_driver_sql("SHOW WARNINGS")).all()
            if any(int(row[1]) not in {1062, 1287} for row in warnings):
                raise PersistenceConflictError("Chat insert violated a storage constraint")
        return MysqlChatCursor(result)

    async def executemany(self, sql: str | ChatSql, parameters: Iterable[Sequence[object]]) -> MysqlChatCursor:
        # Each row uses the same transaction and checks ignored-write warnings.
        result: MysqlChatCursor | None = None
        total = 0
        for values in parameters:
            result = await self.execute(sql, values)
            total += result.rowcount
        if result is None:
            result = MysqlChatCursor(await self.connection.exec_driver_sql("SELECT 1 WHERE FALSE"))
        result.rowcount = total
        return result

    async def execute_fetchall(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> list[MysqlChatRow]:
        return await (await self.execute(sql, parameters)).fetchall()

    async def commit(self) -> None:
        await self.connection.commit()
        self._locked = False

    async def rollback(self) -> None:
        await self.connection.rollback()
        self._locked = False


class MysqlChatDatabase:
    """Bind one logical center to its native chat schema without owning the pool."""

    def __init__(self, database: MysqlDatabase, *, center_id: str) -> None:
        if not center_id.strip():
            raise ValueError("Chat storage requires a center identity")
        self.database = database
        self.center_id = center_id

    async def initialize(self) -> None:
        async with self.database.transaction() as connection:
            owner = (await connection.execute(text(
                "SELECT center_id FROM magi_chat_owner WHERE slot=1 FOR UPDATE"
            ))).scalar_one_or_none()
            if owner is None:
                for table in CHAT_TABLES:
                    if (await connection.execute(text(f"SELECT 1 FROM `{table}` LIMIT 1"))).first() is not None:
                        raise PersistenceConflictError("Unowned chat storage already contains data")
            await connection.execute(text(
                "INSERT INTO magi_chat_owner(slot, center_id) VALUES (1,:center) "
                "ON DUPLICATE KEY UPDATE slot=slot"
            ), {"center": self.center_id})
            owner = (await connection.execute(text(
                "SELECT center_id FROM magi_chat_owner WHERE slot=1 FOR UPDATE"
            ))).scalar_one()
            if owner != self.center_id:
                raise PersistenceConflictError("Chat storage belongs to another center")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[MysqlAsyncChatConnection]:
        async with self.database.transaction() as connection:
            session = MysqlAsyncChatConnection(connection, self.center_id)
            await session.begin_write()
            try:
                yield session
            finally:
                # A workflow must commit explicitly; early returns keep no partial writes.
                await finish_cleanup(session.rollback())
