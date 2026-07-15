from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

import aiosqlite
import pytest

from magi.core.sqlite import (
    connect_aiosqlite,
    connect_sqlite,
    sqlite_connection_async,
    sqlite_transaction,
    sqlite_transaction_async,
)


@pytest.mark.asyncio
async def test_connect_aiosqlite_applies_shared_pragmas_and_row_factory(tmp_path) -> None:
    db_path = tmp_path / "shared_async.db"

    db = await connect_aiosqlite(db_path)
    try:
        journal_row = await (await db.execute("PRAGMA journal_mode")).fetchone()
        sync_row = await (await db.execute("PRAGMA synchronous")).fetchone()
        timeout_row = await (await db.execute("PRAGMA busy_timeout")).fetchone()
        fk_row = await (await db.execute("PRAGMA foreign_keys")).fetchone()

        assert db.row_factory is aiosqlite.Row
        assert str(journal_row[0]).lower() == "wal"
        assert int(timeout_row[0]) == 30000
        assert int(fk_row[0]) == 1
        assert int(sync_row[0]) in {1, 2}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_connect_aiosqlite_closes_partial_connection_when_cancelled(
    monkeypatch,
    tmp_path,
) -> None:
    configuration_started = asyncio.Event()

    class PartialConnection:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    connection = PartialConnection()

    async def fake_connect(*args: Any, **kwargs: Any) -> PartialConnection:
        del args, kwargs
        return connection

    async def blocked_configuration(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        configuration_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("magi.core.sqlite.aiosqlite.connect", fake_connect)
    monkeypatch.setattr("magi.core.sqlite.configure_aiosqlite", blocked_configuration)

    task = asyncio.create_task(connect_aiosqlite(tmp_path / "cancelled.db"))
    await configuration_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert connection.closed is True


def test_connect_sqlite_applies_shared_pragmas_and_row_factory(tmp_path) -> None:
    db_path = tmp_path / "shared_sync.db"

    conn = connect_sqlite(db_path)
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]

        assert conn.row_factory is sqlite3.Row
        assert str(journal_mode).lower() == "wal"
        assert int(synchronous) in {1, 2}
        assert int(busy_timeout) == 30000
        assert int(foreign_keys) == 1
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_sqlite_transaction_async_rolls_back_on_error(tmp_path) -> None:
    db_path = tmp_path / "tx_async.db"
    bootstrap = await connect_aiosqlite(db_path, use_row_factory=False)
    try:
        await bootstrap.execute("CREATE TABLE test_items (value TEXT)")
        await bootstrap.commit()
    finally:
        await bootstrap.close()

    with pytest.raises(RuntimeError):
        async with sqlite_transaction_async(db_path, use_row_factory=False) as db:
            await db.execute("INSERT INTO test_items(value) VALUES ('hello')")
            raise RuntimeError("boom")

    check = await connect_aiosqlite(db_path, use_row_factory=False)
    try:
        row = await (await check.execute("SELECT COUNT(*) FROM test_items")).fetchone()
        assert int(row[0]) == 0
    finally:
        await check.close()


@pytest.mark.asyncio
async def test_sqlite_connection_async_closes_connection_after_context(tmp_path) -> None:
    db_path = tmp_path / "ctx_async.db"

    async with sqlite_connection_async(db_path) as db:
        row = await (await db.execute("PRAGMA journal_mode")).fetchone()
        assert str(row[0]).lower() == "wal"


def test_sqlite_transaction_rolls_back_on_error(tmp_path) -> None:
    db_path = tmp_path / "tx_sync.db"
    conn = connect_sqlite(db_path, use_row_factory=False)
    try:
        conn.execute("CREATE TABLE test_items (value TEXT)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError):
        with sqlite_transaction(db_path, use_row_factory=False) as conn:
            conn.execute("INSERT INTO test_items(value) VALUES ('hello')")
            raise RuntimeError("boom")

    conn = connect_sqlite(db_path, use_row_factory=False)
    try:
        row = conn.execute("SELECT COUNT(*) FROM test_items").fetchone()
        assert int(row[0]) == 0
    finally:
        conn.close()
