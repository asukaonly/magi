"""Atomic event repository contracts independent of embedding execution."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.db.runner import run_upgrade_database
from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l1.ports import EventAppend, EventAppendResult, EventEvidence, EventQuery
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


@pytest.mark.asyncio
async def test_filtered_queries_and_windows_return_decoded_records(repository):
    repo, _path = repository
    for index, user in enumerate(["local_user", "other", "local_user"]):
        value = command(f"event-{index}")
        value.event.user_id = user
        value.event.timestamp = float(index + 1)
        await repo.append(value)
    selected = await repo.query_events(EventQuery(
        user_id="local_user", query="爵士乐", limit=1, offset=1, order_by="timestamp_asc",
    ))
    assert [record.event.event_id for record in selected] == ["event-2"]
    assert selected[0].event.metadata_json["origin"] == "手机"
    assert await repo.query_events(EventQuery(l1_retrieval_scopes=[])) == []
    window = await repo.query_session_event_window(
        session_id="session", center_session_seq=1, window=1, user_id="local_user",
        include_metadata_json=False,
    )
    assert [(record.event.event_id, record.event.session_seq) for record in window] == [
        ("event-0", 0), ("event-2", 2),
    ]
    assert all(record.event.metadata_json is None for record in window)
    hydrated = await repo.fetch_events(
        ["event-2", "absent", "event-1", "event-0", "event-2"], user_id="local_user",
    )
    assert [record.event.event_id for record in hydrated] == ["event-2", "event-0", "event-2"]


@pytest.mark.asyncio
async def test_evidence_reads_hide_deleted_sources_but_maintenance_keeps_identity(repository):
    repo, path = repository
    for event_id in ["active", "deleted"]:
        value = command(event_id, key=f"key:{event_id}")
        value.event.turn_id = f"turn:{event_id}"
        await repo.append(value)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET deleted_at = 100 WHERE event_id = 'deleted'")
    requested = ["deleted", "absent", "active", "deleted"]
    assert set(await repo.get_event_timestamps(requested)) == {"active"}
    evidence = await repo.get_evidence_records(requested)
    assert set(evidence) == {"active"}
    assert evidence["active"]["author_type"] == "user"
    assert evidence["active"]["metadata_json"]["origin"] == "手机"
    assert await repo.get_raw_event_turn_ids(requested) == {
        "deleted": "turn:deleted", "active": "turn:active",
    }
    identities = await repo.get_raw_event_source_identities(requested)
    assert list(identities) == ["deleted", "active"]
    assert identities["deleted"]["was_active"] is False
    assert identities["active"]["was_active"] is True
    assert identities["deleted"]["idempotency_key"] == "key:deleted"


@pytest.mark.asyncio
async def test_facet_rebuild_holds_source_until_concurrent_deletion_finishes(repository, monkeypatch):
    repo, path = repository
    value = command("source")
    value.event.metadata_json = {"source_facets": [{"name": "topic", "text": "jazz"}]}
    value = replace(value, metadata=value.event.metadata_json)
    await repo.append(value)
    store = L1EventStore(db_path=str(path), event_repository=repo, vector_enabled=False)
    await store.initialize()
    read_source = asyncio.Event()
    allow_write = asyncio.Event()
    original = repo._replace_source_facets_for_event

    async def pause_after_read(db, event):
        read_source.set()
        await allow_write.wait()
        await original(db, event)

    monkeypatch.setattr(repo, "_replace_source_facets_for_event", pause_after_read)
    rebuilding = asyncio.create_task(repo.rebuild_source_facets())
    await asyncio.wait_for(read_source.wait(), 5)

    async def forget():
        await store.mark_deleted("source")
        return await store.purge_deleted_events(["source"])

    deleting = asyncio.create_task(forget())
    try:
        await asyncio.sleep(0.05)
        assert not deleting.done()
        allow_write.set()
        assert await rebuilding == {"processed": 1, "indexed": 1}
        assert await deleting == 1
        assert await repo.list_source_facets(event_id="source") == []
        assert await repo.get("source") is None
        assert await repo.rebuild_source_facets() == {"processed": 0, "indexed": 0}
    finally:
        allow_write.set()
        await asyncio.gather(rebuilding, deleting, return_exceptions=True)
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("through_service", [False, True])
async def test_purge_never_removes_active_event_side_records_or_vectors(repository, through_service):
    repo, path = repository
    for event_id in ["active", "deleted"]:
        await repo.append(command(event_id))
    with sqlite3.connect(path) as db:
        for event_id in ["active", "deleted"]:
            db.execute(
                "INSERT INTO l1_event_chunks "
                "(chunk_id, event_id, chunk_index, chunk_text, char_start, char_end, "
                "token_estimate, embedding_profile_id, created_at, updated_at) "
                "VALUES (?, ?, 0, 'retained text', 0, 13, 3, 'model:profile', 1, 1)",
                (f"{event_id}::chunk-0", event_id),
            )
        db.execute("UPDATE fact_events SET deleted_at = 100 WHERE event_id = 'deleted'")
    store = L1EventStore(db_path=str(path), event_repository=repo, vector_enabled=False)
    await store.initialize()
    vectors = SimpleNamespace(delete_entity=AsyncMock(), close=AsyncMock())
    store._vector_index = vectors
    try:
        target = store if through_service else repo
        assert await target.purge_deleted_events(["active", "deleted", "absent"]) == 1
        if through_service:
            vectors.delete_entity.assert_awaited_once_with(entity_id="deleted::chunk-0")
        assert await repo.get("active", visibility="active") is not None
        assert await repo.get("deleted") is None
        with sqlite3.connect(path) as db:
            for table in (
                "l1_event_chunks", "l1_event_embedding_state", "l1_event_payload",
                "l1_source_facets", "l1_events_fts",
            ):
                assert db.execute(f"SELECT event_id FROM {table}").fetchall() == [("active",)]
        assert await target.purge_deleted_events(["active"]) == 0
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_cognition_handoff_backoff_and_ack_survive_repository_recreation(repository):
    repo, path = repository
    value = command("pending")
    value.event.cognition_eligible = True
    await repo.append(value)
    assert await repo.list_ready_cognition_handoffs(now=100) == ["pending"]
    for _ in range(10):
        await repo.retry_cognition_handoff("pending", error="temporary failure", now=100)
    restarted = SqliteMemoryEventRepository(str(path))
    assert await restarted.list_ready_cognition_handoffs(now=159.99) == []
    assert await restarted.list_ready_cognition_handoffs(now=160) == ["pending"]
    await restarted.complete_cognition_handoff("pending")
    assert await repo.list_ready_cognition_handoffs(now=1000) == []
    assert await repo.get_pinned_payloads(["pending"]) == {
        "pending": "capture-time full content",
    }
    assert await repo.get("pending", visibility="active") is not None
