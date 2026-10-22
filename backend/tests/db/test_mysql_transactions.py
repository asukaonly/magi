"""Real MySQL transaction checks for repository infrastructure."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select, text

from magi.core.persistence_errors import PersistenceConflictError
from magi.db.mysql import MysqlDatabase, MysqlSettings


def test_mysql_settings_require_explicit_credentials(monkeypatch):
    monkeypatch.delenv("MAGI_MYSQL_TEST_MISSING_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        MysqlDatabase(MysqlSettings(
            host="127.0.0.1", database="magi_test_architecture", user="root",
            password_env="MAGI_MYSQL_TEST_MISSING_PASSWORD", tls=False,
        ))


def test_remote_mysql_requires_verified_tls(monkeypatch):
    monkeypatch.setenv("MAGI_MYSQL_TEST_PASSWORD", "test")
    with pytest.raises(ValueError, match="require TLS"):
        MysqlDatabase(MysqlSettings(
            host="database.example", database="magi_test_architecture", user="root",
            password_env="MAGI_MYSQL_TEST_PASSWORD", tls=False,
        ))


@pytest.fixture
async def mysql_database(monkeypatch):
    port = os.environ.get("MAGI_TEST_MYSQL_PORT")
    if not port:
        pytest.skip("Set MAGI_TEST_MYSQL_PORT to run real MySQL integration")
    monkeypatch.setenv("MAGI_MYSQL_TEST_PASSWORD", os.environ.get("MAGI_TEST_MYSQL_PASSWORD", ""))
    database = MysqlDatabase(MysqlSettings(
        host="127.0.0.1", port=int(port),
        database=os.environ.get("MAGI_TEST_MYSQL_DATABASE", "magi_test_architecture"),
        user=os.environ.get("MAGI_TEST_MYSQL_USER", "root"),
        password_env="MAGI_MYSQL_TEST_PASSWORD", tls=False, pool_size=1,
    ))
    metadata = MetaData()
    table = Table("transaction_test_" + uuid4().hex, metadata,
                  Column("id", Integer, primary_key=True), Column("value", Integer, nullable=False))
    async with database.transaction() as connection:
        await connection.run_sync(metadata.create_all)
    try:
        yield database, table
    finally:
        async with database.transaction() as connection:
            await connection.run_sync(metadata.drop_all)
        await database.close()


async def test_mysql_commits_and_rolls_back_as_one_transaction(mysql_database):
    database, table = mysql_database
    async with database.transaction() as connection:
        await connection.execute(insert(table).values(id=1, value=10))
    with pytest.raises(ValueError, match="abort"):
        async with database.transaction() as connection:
            await connection.execute(insert(table).values(id=2, value=20))
            raise ValueError("abort")
    async with database.transaction() as connection:
        assert (await connection.execute(select(table))).all() == [(1, 10)]


async def test_mysql_conflict_rolls_back_prior_writes(mysql_database):
    database, table = mysql_database
    with pytest.raises(PersistenceConflictError):
        async with database.transaction() as connection:
            await connection.execute(insert(table).values(id=1, value=10))
            await connection.execute(insert(table).values(id=1, value=20))
    async with database.transaction() as connection:
        assert (await connection.execute(select(table))).all() == []


async def test_mysql_cancelled_query_does_not_replay_or_leak_pool_slot(mysql_database):
    database, table = mysql_database
    inserted = asyncio.Event()

    async def interrupted():
        async with database.transaction() as connection:
            await connection.execute(insert(table).values(id=1, value=10))
            inserted.set()
            await connection.execute(text("SELECT SLEEP(10)"))

    task = asyncio.create_task(interrupted())
    await asyncio.wait_for(inserted.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with database.transaction() as connection:
        await connection.execute(insert(table).values(id=2, value=20))
        assert (await connection.execute(select(table))).all() == [(2, 20)]
