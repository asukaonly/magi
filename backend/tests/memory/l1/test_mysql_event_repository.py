"""Event contracts run against real MySQL, including transaction interruption."""

import asyncio
import os
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from magi.core.persistence_errors import PersistenceConflictError
from magi.db.mysql import MysqlDatabase, MysqlSettings
from magi.db.mysql_migrations import upgrade_mysql_l1
from magi.memory.evidence import L1RetrievalScope
from magi.memory.l1.ports import EventAppendResult, EventQuery
from magi.memory.l1.storage.mysql.events import MysqlMemoryEventRepository
from magi.memory.l1.storage.mysql import schema as s
from .test_event_repository import command


@pytest.fixture
async def mysql_environment(monkeypatch):
    port = os.environ.get("MAGI_TEST_MYSQL_PORT")
    if not port:
        pytest.skip("Set MAGI_TEST_MYSQL_PORT for real MySQL event contracts")
    monkeypatch.setenv("MAGI_MYSQL_EVENTS_PASSWORD", os.environ.get("MAGI_TEST_MYSQL_PASSWORD", ""))
    settings = MysqlSettings(
        host="127.0.0.1",
        port=int(port),
        database="magi_test_architecture",
        user=os.environ.get("MAGI_TEST_MYSQL_USER", "root"),
        password_env="MAGI_MYSQL_EVENTS_PASSWORD",
        tls=False,
    )
    admin = MysqlDatabase(settings)
    name = "magi_test_events_" + uuid4().hex
    async with admin.transaction() as connection:
        await connection.execute(
            text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin")
        )
    database = MysqlDatabase(settings.model_copy(update={"database": name}))
    try:
        await upgrade_mysql_l1(database)
        repository = MysqlMemoryEventRepository(database, center_id="center-test")
        await repository.initialize()
        yield repository, database
    finally:
        await database.close()
        async with admin.transaction() as connection:
            await connection.execute(text(f"DROP DATABASE {name}"))
        await admin.close()


async def table_counts(database):
    async with database.transaction() as connection:
        return {
            table.name: (
                await connection.execute(select(func.count()).select_from(table))
            ).scalar_one()
            for table in (s.events, s.embeddings, s.payloads, s.facets, s.sequences, s.sessions)
        }


async def test_concurrent_replay_and_distinct_events_allocate_exact_sequences(mysql_environment):
    repo, database = mysql_environment
    results = await asyncio.gather(
        *[repo.append(command(f"retry-{i}", key="one-message")) for i in range(20)]
    )
    assert sum(result.inserted for result in results) == 1
    assert {result.session_seq for result in results} == {0}
    assert len({result.event_id for result in results}) == 1
    assert set((await table_counts(database)).values()) == {1}
    distinct = await asyncio.gather(*[repo.append(command(f"distinct-{i}")) for i in range(20)])
    assert sorted(result.session_seq for result in distinct) == list(range(1, 21))
    assert (
        await repo.find_by_idempotency(
            source="chat",
            event_type=command("unused").event.event_type,
            idempotency_key="one-message",
        )
        == results[0].event_id
    )


@pytest.mark.parametrize("interruption", ["failure", "cancel"])
async def test_side_record_failure_rolls_back_source_and_sequence(
    mysql_environment, monkeypatch, interruption
):
    repo, database = mysql_environment
    ready = asyncio.Event()
    original = repo._append_side_rows

    async def fail(connection, value, event_key):
        await original(connection, value, event_key)
        ready.set()
        if interruption == "failure":
            raise RuntimeError("Injected side-row failure")
        await asyncio.Event().wait()

    monkeypatch.setattr(repo, "_append_side_rows", fail)
    task = asyncio.create_task(repo.append(command("interrupted")))
    await asyncio.wait_for(ready.wait(), 10)
    if interruption == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="side-row"):
            await task
    assert set((await table_counts(database)).values()) == {0}
    monkeypatch.setattr(repo, "_append_side_rows", original)
    assert (await repo.append(command("interrupted"))).session_seq == 0


async def test_long_unicode_identity_metadata_and_filter_boundaries(mysql_environment):
    repo, _ = mysql_environment
    value = command("设备" * 700, key="消息" * 700)
    value.event.user_id = "用户" * 400
    value.event.session_id = "主题" * 400
    value.event.timestamp = 10
    await repo.append(value)
    found = await repo.get(value.event.event_id)
    assert found.event.metadata_json == value.metadata
    assert found.event.content == "喜欢爵士乐"
    assert found.event.embedding_profile_id == "model:profile"
    query = EventQuery(
        user_id=value.event.user_id,
        session_id=value.event.session_id,
        start_time=10,
        end_time=10,
        source_filters=["chat"],
        query="爵士",
        l1_retrieval_scopes=["fact_authoritative"],
    )
    assert [row.event.event_id for row in await repo.query_events(query)] == [value.event.event_id]
    assert await repo.query_events(replace(query, user_id="other")) == []
    assert await repo.query_events(replace(query, l1_retrieval_scopes=[])) == []
    assert (await repo.query_events(replace(query, include_metadata_json=False)))[
        0
    ].event.metadata_json is None
    assert await repo.count_events(user_id=value.event.user_id) == 1
    assert await repo.fetch_events([value.event.event_id], user_id="other") == []
    assert [
        row.event.event_id for row in await repo.fetch_events(["missing", value.event.event_id])
    ] == [value.event.event_id]
    assert (await repo.get_evidence_records([value.event.event_id]))[value.event.event_id][
        "metadata_json"
    ] == value.metadata


async def test_explicit_sequences_audit_visibility_and_tombstone_dedup(mysql_environment):
    repo, database = mysql_environment
    assert (await repo.append(command("explicit", sequence=7))).session_seq == 7
    assert await repo.append(command("explicit", sequence=999)) == EventAppendResult(
        "explicit", False, 7
    )
    assert (await repo.append(command("following", key="tombstone"))).session_seq == 8
    assert (await repo.append(command("older", sequence=2))).session_seq == 2
    assert (await repo.append(command("last"))).session_seq == 9
    assert [
        row.event.session_seq
        for row in await repo.query_session_event_window(
            session_id="session", center_session_seq=8, window=1
        )
    ] == [7, 8, 9]
    audit = command("audit")
    await repo.append(
        replace(
            audit, evidence=replace(audit.evidence, retrieval_scope=L1RetrievalScope.AUDIT_ONLY)
        )
    )
    assert await repo.get("audit", visibility="user_visible") is None
    assert await repo.get("audit", visibility="active") is not None
    async with database.transaction() as connection:
        await connection.execute(
            update(s.events).where(s.events.c.event_id == "following").values(deleted_at=100)
        )
    assert (await repo.append(command("new", key="tombstone"))).event_id == "following"
    assert await repo.get("following", visibility="active") is None
    assert (await repo.get("following")).deleted_at == 100
    assert (await repo.get_raw_event_source_identities(["following"]))["following"][
        "was_active"
    ] is False


async def test_migration_repeat_and_foreign_center_are_explicit(mysql_environment):
    repo, database = mysql_environment
    await repo.append(command("survives"))
    await upgrade_mysql_l1(database)
    await MysqlMemoryEventRepository(database, center_id="center-test").initialize()
    with pytest.raises(PersistenceConflictError, match="another center"):
        await MysqlMemoryEventRepository(database, center_id="another").initialize()
    assert (await repo.get("survives")).event.content == "喜欢爵士乐"
