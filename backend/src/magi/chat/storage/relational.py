"""Internal connection contracts for shared chat persistence transactions."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol
from .statements import ChatSql


class ChatRow(Protocol):
    """A named result row with stable positional access for aggregate queries."""

    def __getitem__(self, key: str | int) -> Any: ...
    def keys(self) -> Sequence[str]: ...


class AsyncChatCursor(Protocol):
    rowcount: int

    async def fetchone(self) -> ChatRow | None: ...
    async def fetchall(self) -> Sequence[ChatRow]: ...


class AsyncChatConnection(Protocol):
    """Keep transaction ownership with the domain operation, not individual rows."""

    async def begin_write(self) -> None: ...
    async def execute(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> AsyncChatCursor: ...
    async def executemany(self, sql: str | ChatSql, parameters: Iterable[Sequence[object]]) -> AsyncChatCursor: ...
    async def execute_fetchall(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> Sequence[ChatRow]: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class ChatDatabase(Protocol):
    """Own connections while shared repository methods own atomic transitions."""

    async def initialize(self) -> None: ...
    def session(self) -> AbstractAsyncContextManager[AsyncChatConnection]: ...
