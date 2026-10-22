"""Atomic event repository contracts independent of embedding execution."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from magi.db.runner import run_upgrade_database
from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l1.ports import EventAppend, EventAppendResult, EventEvidence
from magi.memory.l1.source_facets import SourceFacet
from magi.memory.l1.storage.events import SqliteMemoryEventRepository


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / "events.db"
    run_upgrade_database("l1", path)
    return SqliteMemoryEventRepository(str(path)), path


def command(event_id: str, *, key: str | None = None, sequence: int | None = None) -> EventAppend:
    event = normalize_runtime_event(Event(
        type=EventTypes.USER_MESSAGE, source="chat", level=EventLevel.INFO,
        event_id=event_id, correlation_id=event_id,
        data={"user_id": "local_user", "session_id": "session", "content": "喜欢爵士乐"},
    ))
    event.idempotency_key = key
    event.session_seq = sequence
    event.pinned_payload = "capture-time full content"
    return EventAppend(
        event=event,
        evidence=EventEvidence(EvidenceStatus.CLASSIFIED, EvidenceClass.UNKNOWN, 1, L1RetrievalScope.FACT_AUTHORITATIVE),
        metadata={"origin": "手机", "nested": {"accepted": True}},
        embedding_status="pending", embedding_profile_id="model:profile",
        search_text=event.content,
        source_facets=(SourceFacet(event_id, "chat", "topic", text_value="爵士乐"),),
    )


def counts(path):
    tables = (
        "fact_events", "l1_event_embedding_state", "l1_event_payload",
        "l1_source_facets", "l1_events_fts", "l1_session_sequences", "chat_sessions",
    )
    with sqlite3.connect(path) as db:
        return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


@pytest.mark.asyncio
async def test_concurrent_replays_commit_one_event_and_one_sequence(repository):
    repo, path = repository
    results = await asyncio.gather(*[
        repo.append(command(f"attempt-{index}", key="same-source-message"))
        for index in range(20)
    ])
    assert sum(result.inserted for result in results) == 1
    assert len({result.event_id for result in results}) == 1
    assert {result.session_seq for result in results} == {0}
    assert set(counts(path).values()) == {1}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT message_count FROM chat_sessions").fetchone()[0] == 1
    assert await repo.find_by_idempotency(
        source="chat", event_type=EventTypes.USER_MESSAGE, idempotency_key="same-source-message",
    ) == results[0].event_id


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["failure", "cancel"])
async def test_interruption_rolls_back_all_rows_and_sequence(repository, monkeypatch, interruption):
    repo, path = repository
    written = asyncio.Event()
    original = repo._write_event_side_tables

    async def interrupt(db, value):
        await original(db, value)
        written.set()
        if interruption == "failure":
            raise RuntimeError("Injected write failure")
        await asyncio.Event().wait()

    monkeypatch.setattr(repo, "_write_event_side_tables", interrupt)
    task = asyncio.create_task(repo.append(command("retryable")))
    await asyncio.wait_for(written.wait(), timeout=5)
    if interruption == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="Injected write failure"):
            await task
    assert set(counts(path).values()) == {0}
    monkeypatch.setattr(repo, "_write_event_side_tables", original)
    assert (await repo.append(command("retryable"))).session_seq == 0
    assert set(counts(path).values()) == {1}


@pytest.mark.asyncio
async def test_explicit_sequences_and_duplicates_preserve_highwater(repository):
    repo, _path = repository
    assert (await repo.append(command("explicit", sequence=7))).session_seq == 7
    duplicate = await repo.append(command("explicit", sequence=999))
    assert duplicate == EventAppendResult("explicit", False, 7)
    assert (await repo.append(command("following"))).session_seq == 8
    assert (await repo.append(command("older", sequence=2))).session_seq == 2
    assert (await repo.append(command("last"))).session_seq == 9


@pytest.mark.asyncio
async def test_deleted_event_is_readable_for_maintenance_but_never_reinserted(repository):
    repo, path = repository
    await repo.append(command("deleted", key="stable-key"))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET deleted_at = 100 WHERE event_id = 'deleted'")
    result = await repo.append(command("new-id", key="stable-key"))
    assert result == EventAppendResult("deleted", False, 0)
    assert await repo.get("deleted", visibility="active") is None
    assert await repo.get("deleted", visibility="user_visible") is None
    record = await repo.get("deleted")
    assert record.deleted_at == 100
    assert record.event.metadata_json == {"origin": "手机", "nested": {"accepted": True}}
    assert record.event.embedding_status == "pending"
    assert record.event.embedding_profile_id == "model:profile"
    assert record.evidence.status is EvidenceStatus.CLASSIFIED
    assert record.evidence.retrieval_scope is L1RetrievalScope.FACT_AUTHORITATIVE
    assert set(counts(path).values()) == {1}


@pytest.mark.asyncio
async def test_audit_events_and_invalid_metadata_do_not_leak_to_product_reads(repository):
    repo, path = repository
    value = command("audit")
    value = replace(value, evidence=replace(value.evidence, retrieval_scope=L1RetrievalScope.AUDIT_ONLY))
    await repo.append(value)
    assert await repo.get("audit", visibility="active") is not None
    assert await repo.get("audit", visibility="user_visible") is None
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET metadata_json = '[]' WHERE event_id = 'audit'")
    with pytest.raises(ValueError, match="metadata must be an object"):
        await repo.get("audit")


@pytest.mark.asyncio
async def test_embedding_is_scheduled_only_after_repository_confirms_insertion(repository):
    repo, path = repository
    store = L1EventStore(db_path=str(path), event_repository=repo, vector_enabled=False)
    schedule = AsyncMock()
    store._schedule_event_embedding = schedule
    first = command("first", key="shared").event
    replay = command("replay", key="shared").event
    try:
        assert await store.store(first) == "first"
        assert await store.store(replay) == "first"
        schedule.assert_awaited_once_with(first)
        assert first.session_seq == replay.session_seq == 0
    finally:
        await store.shutdown()
