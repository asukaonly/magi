from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

import aiosqlite
import pytest

from magi.core.sqlite import (
    configure_aiosqlite,
    configure_sqlite3,
    connect_aiosqlite,
    connect_sqlite,
    secure_compact_sqlite,
    sqlite_connection_async,
    sqlite_transaction,
    sqlite_transaction_async,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "failure,attempts,delays_expected",
    [
        ("transient", 3, [0.01, 0.02]),
        ("io", 1, []),
        ("persistent", 6, [0.01, 0.02, 0.04, 0.08, 0.16]),
    ],
)
async def test_sqlite_journal_retry_policy_and_cursor_ownership(
    monkeypatch, mode, failure, attempts, delays_expected
):
    from types import SimpleNamespace
    import magi.core.sqlite as sqlite_module

    statements = []
    delays = []
    error = sqlite3.OperationalError("disk I/O error" if failure == "io" else "database is locked")

    class Cursor:
        closed = False

        def execute(self, statement):
            statements.append(statement)
            if statement == "PRAGMA journal_mode=WAL":
                count = statements.count(statement)
                if failure != "transient" or count < 3:
                    raise error

        def close(self):
            self.closed = True

    cursor = Cursor()

    class SyncConnection:
        row_factory = None

        def cursor(self):
            return cursor

    class AsyncConnection:
        row_factory = None

        async def execute(self, statement):
            cursor.execute(statement)

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(
        sqlite_module, "time", SimpleNamespace(monotonic=lambda: 0.0, sleep=delays.append)
    )
    monkeypatch.setattr(sqlite_module, "asyncio", SimpleNamespace(sleep=sleep))
    connection = SyncConnection() if mode == "sync" else AsyncConnection()

    async def configure():
        if mode == "sync":
            return configure_sqlite3(connection, use_row_factory=False)
        return await configure_aiosqlite(connection, use_row_factory=False)

    if failure == "transient":
        assert await configure() is connection
    else:
        with pytest.raises(sqlite3.OperationalError) as raised:
            await configure()
        assert raised.value is error
    expected = ["PRAGMA busy_timeout = 250"] + ["PRAGMA journal_mode=WAL"] * attempts
    if failure == "transient":
        expected += [
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys = 1",
            "PRAGMA busy_timeout = 30000",
        ]
    assert statements == expected
    assert delays == delays_expected
    if mode == "sync":
        assert cursor.closed


def test_connect_sqlite_closes_partial_connection_when_configuration_fails(
    monkeypatch,
    tmp_path,
) -> None:
    class PartialConnection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    connection = PartialConnection()

    def fail_configuration(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError("configuration failed")

    monkeypatch.setattr("magi.core.sqlite.sqlite3.connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr("magi.core.sqlite.configure_sqlite3", fail_configuration)

    with pytest.raises(RuntimeError, match="configuration failed"):
        connect_sqlite(tmp_path / "partial.db")

    assert connection.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_real_sqlite_connection_recovers_after_observed_journal_contention(
    tmp_path, monkeypatch, mode
):
    import magi.core.sqlite as sqlite_module

    db_path = tmp_path / "contended.db"
    blocker = sqlite3.connect(db_path)
    blocker.execute("CREATE TABLE test_items(value TEXT)")
    blocker.commit()
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO test_items VALUES ('held')")
    loop = asyncio.get_running_loop()
    retried = asyncio.Event()
    retry_delay = sqlite_module._journal_mode_retry_delay

    def observe_retry(attempt):
        loop.call_soon_threadsafe(retried.set)
        return retry_delay(attempt)

    monkeypatch.setattr(sqlite_module, "_journal_mode_retry_delay", observe_retry)

    def sync_read():
        db = connect_sqlite(db_path)
        try:
            return (
                db.execute("PRAGMA journal_mode").fetchone()[0],
                db.execute("SELECT value FROM test_items").fetchone()[0],
            )
        finally:
            db.close()

    async def async_read():
        db = await connect_aiosqlite(db_path)
        try:
            return (await (await db.execute("PRAGMA journal_mode")).fetchone())[0], (
                await (await db.execute("SELECT value FROM test_items")).fetchone()
            )[0]
        finally:
            await db.close()

    task = asyncio.create_task(asyncio.to_thread(sync_read) if mode == "sync" else async_read())
    try:
        await asyncio.wait_for(retried.wait(), 2)
        assert not task.done()
        blocker.commit()
        assert await asyncio.wait_for(task, 2) == ("wal", "held")
    finally:
        blocker.close()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_real_connection_enforces_shared_sqlite_policy(tmp_path, mode):
    path = tmp_path / "policy.db"
    names = ["journal_mode", "synchronous", "busy_timeout", "foreign_keys"]
    if mode == "sync":
        db = connect_sqlite(path)
        try:
            assert db.row_factory is sqlite3.Row
            values = [db.execute(f"PRAGMA {name}").fetchone()[0] for name in names]
        finally:
            db.close()
    else:
        db = await connect_aiosqlite(path)
        try:
            assert db.row_factory is aiosqlite.Row
            values = [(await (await db.execute(f"PRAGMA {name}")).fetchone())[0] for name in names]
        finally:
            await db.close()
    assert values == ["wal", 1, 30000, 1]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("fail", [False, True])
async def test_transactions_commit_or_rollback_without_losing_existing_rows(tmp_path, mode, fail):
    from contextlib import closing, nullcontext

    path = tmp_path / "transaction.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE test_items(value TEXT)")
        db.execute("INSERT INTO test_items VALUES ('existing')")
        db.commit()
    try:
        with pytest.raises(RuntimeError, match="Business failure") if fail else nullcontext():
            if mode == "sync":
                with sqlite_transaction(path, use_row_factory=False) as transaction:
                    transaction.execute("INSERT INTO test_items VALUES ('new')")
                    if fail:
                        raise RuntimeError("Business failure")
            else:
                async with sqlite_transaction_async(path, use_row_factory=False) as transaction:
                    await transaction.execute("INSERT INTO test_items VALUES ('new')")
                    if fail:
                        raise RuntimeError("Business failure")
        with closing(sqlite3.connect(path)) as check:
            assert check.execute("SELECT value FROM test_items ORDER BY rowid").fetchall() == (
                [("existing",)] if fail else [("existing",), ("new",)]
            )
        if mode == "sync":
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                transaction.execute("SELECT 1")
        else:
            with pytest.raises(ValueError, match="no active connection"):
                await transaction.execute("SELECT 1")
    finally:
        db.close()


@pytest.mark.asyncio
async def test_sqlite_connection_async_closes_connection_after_context(tmp_path) -> None:
    db_path = tmp_path / "ctx_async.db"

    async with sqlite_connection_async(db_path) as db:
        row = await (await db.execute("PRAGMA journal_mode")).fetchone()
        assert str(row[0]).lower() == "wal"

    with pytest.raises(ValueError, match="no active connection"):
        await db.execute("SELECT 1")


@pytest.mark.asyncio
async def test_secure_compact_sqlite_removes_deleted_payload_bytes(tmp_path) -> None:
    db_path = tmp_path / "private_content.db"
    private_marker = "magi-private-content-" + ("x" * 512)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA secure_delete=OFF")
        conn.execute("CREATE TABLE private_items (payload TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO private_items(payload) VALUES (?)",
            (private_marker,),
        )
        conn.commit()
        conn.execute("DELETE FROM private_items")
        conn.commit()
    finally:
        conn.close()

    assert private_marker.encode() in db_path.read_bytes()

    await secure_compact_sqlite(db_path)

    for suffix in ("", "-wal", "-shm"):
        candidate = tmp_path / f"{db_path.name}{suffix}"
        if candidate.exists():
            assert private_marker.encode() not in candidate.read_bytes()


@pytest.mark.asyncio
async def test_secure_compact_sqlite_does_not_create_missing_database(tmp_path) -> None:
    db_path = tmp_path / "missing.db"

    await secure_compact_sqlite(db_path)

    assert not db_path.exists()


@pytest.mark.asyncio
async def test_cancelled_sqlite_open_drains_thread_before_returning(monkeypatch, tmp_path):
    import threading

    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    closed = threading.Event()
    real_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            super().close()
            closed.set()

    def blocked_connect(*args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise RuntimeError("Test did not release SQLite open")
        return real_connect(*args, **kwargs, factory=TrackedConnection)

    monkeypatch.setattr("magi.core.sqlite.sqlite3.connect", blocked_connect)
    task = asyncio.create_task(connect_aiosqlite(tmp_path / "cancelled-open.db"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "Cancellation must retain ownership of the opening thread"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set(), "Cancelled open must close its newly created database"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(closed.wait, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [sqlite_connection_async, sqlite_transaction_async])
async def test_cancelled_sqlite_close_drains_thread_before_returning(
    monkeypatch, tmp_path, context
):
    import threading

    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    closed = threading.Event()
    real_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise RuntimeError("Test did not release SQLite close")
            super().close()
            closed.set()

    monkeypatch.setattr(
        "magi.core.sqlite.sqlite3.connect",
        lambda *args, **kwargs: real_connect(*args, **kwargs, factory=TrackedConnection),
    )

    async def use_connection():
        async with context(tmp_path / "cancelled-close.db") as db:
            await db.execute("CREATE TABLE test_items (value TEXT)")

    task = asyncio.create_task(use_connection())
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "Repeated cancellation must wait for SQLite close"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(closed.wait, 1)
