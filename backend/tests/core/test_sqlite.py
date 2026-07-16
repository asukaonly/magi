from __future__ import annotations

import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import aiosqlite
import pytest

from magi.core.sqlite import (
    configure_aiosqlite,
    configure_sqlite3,
    connect_aiosqlite,
    connect_sqlite,
    sqlite_connection_async,
    sqlite_transaction,
    sqlite_transaction_async,
)


@pytest.mark.asyncio
async def test_configure_aiosqlite_retries_only_locked_journal_mode_after_busy_timeout(
    monkeypatch,
) -> None:
    statements: list[str] = []
    delays: list[float] = []
    journal_attempts = 0

    class LockedAsyncConnection:
        row_factory = None

        async def execute(self, statement: str) -> object:
            nonlocal journal_attempts
            statements.append(statement)
            if statement.startswith("PRAGMA journal_mode"):
                journal_attempts += 1
                if journal_attempts < 3:
                    raise sqlite3.OperationalError("database is locked")
            return object()

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("magi.core.sqlite.asyncio.sleep", record_sleep)
    connection = LockedAsyncConnection()

    result = await configure_aiosqlite(
        cast(aiosqlite.Connection, connection),
        use_row_factory=False,
    )

    assert result is connection
    assert statements[0] == "PRAGMA busy_timeout = 250"
    assert statements[-1] == "PRAGMA busy_timeout = 30000"
    assert statements.count("PRAGMA journal_mode=WAL") == 3
    assert statements.index("PRAGMA synchronous=NORMAL") > max(
        index
        for index, statement in enumerate(statements)
        if statement == "PRAGMA journal_mode=WAL"
    )
    assert delays == [0.01, 0.02]


def test_configure_sqlite3_retries_only_locked_journal_mode_after_busy_timeout(
    monkeypatch,
) -> None:
    statements: list[str] = []
    delays: list[float] = []
    journal_attempts = 0

    class LockedCursor:
        closed = False

        def execute(self, statement: str) -> object:
            nonlocal journal_attempts
            statements.append(statement)
            if statement.startswith("PRAGMA journal_mode"):
                journal_attempts += 1
                if journal_attempts < 3:
                    raise sqlite3.OperationalError("database is locked")
            return object()

        def close(self) -> None:
            self.closed = True

    class LockedConnection:
        row_factory = None

        def __init__(self) -> None:
            self.test_cursor = LockedCursor()

        def cursor(self) -> LockedCursor:
            return self.test_cursor

    monkeypatch.setattr("magi.core.sqlite.time.sleep", delays.append)
    connection = LockedConnection()

    result = configure_sqlite3(
        cast(sqlite3.Connection, connection),
        use_row_factory=False,
    )

    assert result is connection
    assert statements[0] == "PRAGMA busy_timeout = 250"
    assert statements[-1] == "PRAGMA busy_timeout = 30000"
    assert statements.count("PRAGMA journal_mode=WAL") == 3
    assert statements.index("PRAGMA synchronous=NORMAL") > max(
        index
        for index, statement in enumerate(statements)
        if statement == "PRAGMA journal_mode=WAL"
    )
    assert delays == [0.01, 0.02]
    assert connection.test_cursor.closed is True


@pytest.mark.asyncio
async def test_configure_aiosqlite_does_not_retry_non_lock_error(monkeypatch) -> None:
    error = sqlite3.OperationalError("disk I/O error")
    statements: list[str] = []
    delays: list[float] = []

    class FailingAsyncConnection:
        row_factory = None

        async def execute(self, statement: str) -> object:
            statements.append(statement)
            if statement.startswith("PRAGMA journal_mode"):
                raise error
            return object()

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("magi.core.sqlite.asyncio.sleep", record_sleep)

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        await configure_aiosqlite(
            cast(aiosqlite.Connection, FailingAsyncConnection()),
            use_row_factory=False,
        )

    assert exc_info.value is error
    assert statements.count("PRAGMA journal_mode=WAL") == 1
    assert delays == []


def test_configure_sqlite3_does_not_retry_non_lock_error(monkeypatch) -> None:
    error = sqlite3.OperationalError("disk I/O error")
    statements: list[str] = []
    delays: list[float] = []

    class FailingCursor:
        def execute(self, statement: str) -> object:
            statements.append(statement)
            if statement.startswith("PRAGMA journal_mode"):
                raise error
            return object()

        def close(self) -> None:
            return None

    class FailingConnection:
        row_factory = None

        def cursor(self) -> FailingCursor:
            return FailingCursor()

    monkeypatch.setattr("magi.core.sqlite.time.sleep", delays.append)

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        configure_sqlite3(
            cast(sqlite3.Connection, FailingConnection()),
            use_row_factory=False,
        )

    assert exc_info.value is error
    assert statements.count("PRAGMA journal_mode=WAL") == 1
    assert delays == []


@pytest.mark.asyncio
async def test_configure_aiosqlite_reraises_persistent_journal_mode_lock(
    monkeypatch,
) -> None:
    error = sqlite3.OperationalError("database is locked")
    statements: list[str] = []
    delays: list[float] = []

    class LockedAsyncConnection:
        row_factory = None

        async def execute(self, statement: str) -> object:
            statements.append(statement)
            if statement.startswith("PRAGMA journal_mode"):
                raise error
            return object()

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("magi.core.sqlite.asyncio.sleep", record_sleep)

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        await configure_aiosqlite(
            cast(aiosqlite.Connection, LockedAsyncConnection()),
            use_row_factory=False,
        )

    assert exc_info.value is error
    assert statements.count("PRAGMA journal_mode=WAL") == 6
    assert delays == [0.01, 0.02, 0.04, 0.08, 0.16]


def test_configure_sqlite3_reraises_persistent_journal_mode_lock(monkeypatch) -> None:
    error = sqlite3.OperationalError("database is locked")
    statements: list[str] = []
    delays: list[float] = []

    class LockedCursor:
        def execute(self, statement: str) -> object:
            statements.append(statement)
            if statement.startswith("PRAGMA journal_mode"):
                raise error
            return object()

        def close(self) -> None:
            return None

    class LockedConnection:
        row_factory = None

        def cursor(self) -> LockedCursor:
            return LockedCursor()

    monkeypatch.setattr("magi.core.sqlite.time.sleep", delays.append)

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        configure_sqlite3(
            cast(sqlite3.Connection, LockedConnection()),
            use_row_factory=False,
        )

    assert exc_info.value is error
    assert statements.count("PRAGMA journal_mode=WAL") == 6
    assert delays == [0.01, 0.02, 0.04, 0.08, 0.16]


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
async def test_connect_aiosqlite_waits_for_concurrent_journal_mode_lock(tmp_path) -> None:
    db_path = tmp_path / "async_journal_lock.db"
    blocker = sqlite3.connect(db_path)
    blocker.execute("CREATE TABLE test_items (value TEXT)")
    blocker.commit()
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO test_items(value) VALUES ('held')")

    task = asyncio.create_task(connect_aiosqlite(db_path))
    await asyncio.sleep(0.05)
    blocker.commit()
    blocker.close()

    db = await asyncio.wait_for(task, timeout=2)
    try:
        row = await (await db.execute("PRAGMA journal_mode")).fetchone()
        assert str(row[0]).lower() == "wal"
    finally:
        await db.close()


def test_connect_sqlite_waits_for_concurrent_journal_mode_lock(tmp_path) -> None:
    db_path = tmp_path / "sync_journal_lock.db"
    blocker = sqlite3.connect(db_path)
    blocker.execute("CREATE TABLE test_items (value TEXT)")
    blocker.commit()
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO test_items(value) VALUES ('held')")

    def connect_read_and_close() -> str:
        conn = connect_sqlite(db_path)
        try:
            return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(connect_read_and_close)
        time.sleep(0.05)
        blocker.commit()
        blocker.close()
        journal_mode = future.result(timeout=2)

    assert journal_mode == "wal"


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
