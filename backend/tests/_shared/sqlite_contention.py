"""Observe SQLite writer contention without replacing database transactions."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace


def hold_first_transaction(monkeypatch, module):
    gate = SimpleNamespace(first_locked=asyncio.Event(), second_attempted=asyncio.Event(), release_first=asyncio.Event())
    original_connection = module.sqlite_connection_async
    attempts = 0

    @asynccontextmanager
    async def connection(*args, **kwargs):
        async with original_connection(*args, **kwargs) as db:
            original_execute = db.execute

            async def begin(sql, *args, **kwargs):
                nonlocal attempts
                attempts += 1
                ordinal = attempts
                if ordinal == 2:
                    gate.second_attempted.set()
                result = await original_execute(sql, *args, **kwargs)
                if ordinal == 1:
                    gate.first_locked.set()
                    await gate.release_first.wait()
                return result

            def execute(sql, *args, **kwargs):
                if sql == "BEGIN IMMEDIATE":
                    return begin(sql, *args, **kwargs)
                return original_execute(sql, *args, **kwargs)

            monkeypatch.setattr(db, "execute", execute)
            yield db

    monkeypatch.setattr(module, "sqlite_connection_async", connection)
    return gate
