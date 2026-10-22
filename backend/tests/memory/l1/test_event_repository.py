"""Atomic event repository contracts independent of embedding execution."""

from __future__ import annotations

from _shared.memory_stores import build_l1_store

import asyncio
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.core.persistence_errors import PersistenceConflictError

from magi.db.runner import run_upgrade_database
from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
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
    store = build_l1_store(db_path=str(path), event_repository=repo, vector_enabled=False)
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
    store = build_l1_store(db_path=str(path), event_repository=repo, vector_enabled=False)
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
    store = build_l1_store(db_path=str(path), event_repository=repo, vector_enabled=False)
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


@pytest.mark.asyncio
async def test_lexical_candidates_recheck_authoritative_visibility(repository):
    repo, path = repository
    for event_id in ["active", "deleted", "missing"]:
        value = replace(command(event_id), search_text="hummingbird")
        await repo.append(value)
    # Simulate an index that has not received source deletion yet.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET deleted_at = 100 WHERE event_id = 'deleted'")
        db.execute("DELETE FROM fact_events WHERE event_id = 'missing'")
    for options in ({}, {"user_id": "local_user"}, {"start_time": 0}, {"strict": True}):
        matches = await repo.bm25_search("hummingbird", **options)
        assert [event_id for event_id, _score in matches] == ["active"]
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM l1_events_fts")
    assert await repo.backfill_fts(batch_size=1) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT event_id FROM l1_events_fts").fetchall() == [("active",)]


@pytest.mark.asyncio
async def test_entity_link_generation_is_authoritative_after_repository_restart(repository):
    repo, path = repository
    assert await repo.replace_projected_event_entities_batch(projections=[
        ("source", 1, "lease", 1, 0, [("entity:jazz", "topic", 0.8)]),
    ])
    assert await repo.align_entity_link_projection_clear_generation(1) == 1
    restarted = SqliteMemoryEventRepository(str(path))
    assert not await restarted.replace_projected_event_entities_batch(projections=[
        ("source", 2, "old-worker", 1, 0, [("entity:jazz", "topic", 0.8)]),
    ])
    assert await restarted.resolve_event_entities(["source"]) == []
    with pytest.raises(RuntimeError, match="cannot move backwards"):
        await restarted.align_entity_link_projection_clear_generation(0)


async def embedding_publication(repo, event_id):
    from magi.memory.embedding.chunking import chunk_sentences
    from magi.memory.embedding.embedding_service import EmbeddingProfile
    from magi.memory.l1.embedding_contracts import EventEmbeddingPublication, EventEmbeddingSource

    source = EventEmbeddingSource.from_event((await repo.get(event_id)).event)
    profile = EmbeddingProfile.build(
        provider_name="test", model_name="encoder", dimension=3, text_builder_version="l1_content_v2",
    )
    return EventEmbeddingPublication(
        source=source, status="ready", profile_id=profile.profile_id, profile=profile,
        chunks=tuple(chunk_sentences(source.text)), embedded_at=123,
    )


@pytest.mark.asyncio
async def test_embedding_chunks_profile_and_state_roll_back_together(repository):
    repo, path = repository
    await repo.append(command("source"))
    publication = await embedding_publication(repo, "source")
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER reject_ready BEFORE UPDATE ON l1_event_embedding_state
            WHEN NEW.embedding_status = 3 BEGIN SELECT RAISE(ABORT, 'state unavailable'); END""")
    with pytest.raises(PersistenceConflictError, match="persistence constraint"):
        await repo.publish_event_embeddings([publication])
    assert await repo.fetch_embedding_chunks(["source::chunk-0"]) == []
    assert (await repo.get("source")).event.embedding_status == "pending"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM embedding_profiles").fetchone()[0] == 0
        db.execute("DROP TRIGGER reject_ready")
    assert await repo.publish_event_embeddings([publication]) == {"source"}
    result = await repo.get("source")
    assert result.event.embedding_status == "ready"
    assert result.embedding_chunk_count == len(publication.chunks)
    assert result.last_embedded_at == 123
    assert await repo.visible_embedding_chunk_ids(["source::chunk-0", "missing"]) == {"source::chunk-0"}


@pytest.mark.asyncio
async def test_stale_embedding_publications_and_removals_do_not_modify_current_source(repository):
    repo, path = repository
    await repo.append(command("source"))
    old = await embedding_publication(repo, "source")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET content = 'Changed source text' WHERE event_id = 'source'")
    current = await embedding_publication(repo, "source")
    assert await repo.publish_event_embeddings([old]) == set()
    assert await repo.publish_event_embeddings([current]) == {"source"}
    assert await repo.remove_event_embedding_chunks([old.source]) == []
    assert (await repo.get("source")).event.embedding_status == "ready"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET deleted_at = 100 WHERE event_id = 'source'")
    assert await repo.publish_event_embeddings([current]) == set()
    assert await repo.visible_embedding_chunk_ids(["source::chunk-0"]) == set()
    assert await repo.fetch_embedding_chunks(["source::chunk-0"]) == []


@pytest.mark.asyncio
async def test_clear_rolls_back_all_source_rows_and_preserves_database_schema(repository):
    repo, path = repository
    await repo.append(command("source"))
    await repo.replace_projected_event_entities_batch(projections=[
        ("source", 1, "lease", 1, 0, [("entity:jazz", "topic", 1.0)]),
    ])
    identity = path.stat().st_ino
    with sqlite3.connect(path) as db:
        version = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        db.execute("CREATE TABLE independent_owner (value TEXT)")
        db.execute("INSERT INTO independent_owner VALUES ('retained')")
        db.execute("""CREATE TRIGGER reject_clear BEFORE DELETE ON fact_events
            BEGIN SELECT RAISE(ABORT, 'clear interrupted'); END""")
    with pytest.raises(PersistenceConflictError, match="persistence constraint"):
        await repo.clear_events(entity_link_clear_generation=1)
    assert set(counts(path).values()) == {1}
    assert (await repo.get_clear_state()).entity_link_generation == 0
    assert await repo.resolve_event_entities(["source"]) == ["entity:jazz"]
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER reject_clear")
    assert await repo.clear_events(entity_link_clear_generation=1) == 1
    assert set(counts(path).values()) == {0}
    assert await repo.resolve_event_entities(["source"]) == []
    assert (await repo.get_clear_state()).entity_link_generation == 1
    assert path.stat().st_ino == identity
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == version
        assert db.execute("SELECT value FROM independent_owner").fetchall() == [("retained",)]


@pytest.mark.asyncio
async def test_evidence_scan_reports_invalid_rows_and_rejects_obsolete_updates(repository):
    from magi.memory.l1.maintenance_contracts import EvidenceAnnotationUpdate, EvidenceBackfillQuery
    repo, path = repository
    for event_id in ["valid", "replaced", "deleted", "invalid"]:
        await repo.append(command(event_id))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET metadata_json = '[]' WHERE event_id = 'invalid'")
    query = EvidenceBackfillQuery()
    high_water = await repo.event_scan_high_water()
    page = await repo.scan_evidence_backfill(query, after=0, through=high_water, limit=10)
    assert len(page) == 4
    assert page[-1].record is None
    assert "metadata must be an object" in page[-1].error
    evidence = EventEvidence(EvidenceStatus.CLASSIFIED, EvidenceClass.USER_SELF_REPORT, 99, L1RetrievalScope.FACT_AUTHORITATIVE)
    updates = [EvidenceAnnotationUpdate(item.record, evidence) for item in page if item.record is not None]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fact_events SET content = 'changed' WHERE event_id = 'replaced'")
        db.execute("UPDATE fact_events SET deleted_at = 100 WHERE event_id = 'deleted'")
    assert await repo.apply_evidence_annotations(updates) == 1
    assert (await repo.get("valid")).evidence.rule_version == 99
    assert (await repo.get("replaced")).evidence.rule_version == 1
    assert (await repo.get("deleted")).evidence.rule_version == 1
    await repo.append(command("after-scan"))
    assert await repo.scan_evidence_backfill(query, after=page[-1].sequence, through=high_water, limit=10) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "lexical", "payload", "initialize"])
async def test_storage_failure_does_not_escape_as_driver_error_or_empty_success(tmp_path, operation):
    from magi.core.persistence_errors import PersistenceUnavailableError
    # An existing empty database has no migrated event schema.
    path = tmp_path / "unmigrated.db"
    sqlite3.connect(path).close()
    repo = SqliteMemoryEventRepository(str(path))
    with pytest.raises(PersistenceUnavailableError, match="did not confirm"):
        if operation == "get":
            await repo.get("missing")
        elif operation == "lexical":
            await repo.bm25_search("hummingbird")
        elif operation == "payload":
            await repo.get_pinned_payloads(["missing"])
        else:
            await repo.initialize()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


@pytest.mark.asyncio
async def test_event_service_runs_with_pathless_repository_and_no_driver(monkeypatch):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l1.maintenance_contracts import EventClearState
    from magi.memory.l1.ports import MemoryEventRecord, MemoryEventRepository
    from unittest.mock import Mock
    import magi.core.sqlite as sqlite_driver

    def unexpected_driver(*_args, **_kwargs):
        raise AssertionError("Business service attempted to open a database")

    monkeypatch.setattr(sqlite_driver, "connect_aiosqlite", unexpected_driver)
    repo = AsyncMock(spec=MemoryEventRepository)
    value = command("pathless")
    repo.append.return_value = EventAppendResult("pathless", True, 0)
    repo.get.return_value = MemoryEventRecord(value.event, value.evidence, 0, None, None)
    repo.count_events.return_value = 1
    repo.get_clear_state.return_value = EventClearState(0, False)
    repo.clear_events.return_value = 1
    indexes = SimpleNamespace(create=Mock(side_effect=unexpected_driver))
    store = L1EventStore(event_repository=repo, vector_index_factory=indexes, vector_enabled=False)
    assert not hasattr(store, "db_path")
    assert await store.store(value.event) == "pathless"
    assert (await store.get_event("pathless"))["content"] == value.event.content
    assert await store.clear(restart_workers=False) == 1
    repo.clear_events.assert_awaited_once_with(entity_link_clear_generation=None)
    assert "db_path" not in store.get_statistics()
    await store.shutdown()


async def assert_exact_message_retirement_scope(repo):
    for event_id, session_id, user_id in (("selected", "room-a", "owner"), ("other-room", "room-b", "owner"), ("other-user", "room-a", "other")):
        value = command(event_id)
        value.event.session_id = session_id
        value.event.user_id = user_id
        value.event.source_item_id = "same-platform-message-id"
        await repo.append(value)
    await repo.soft_delete_events(["selected", "other-room", "other-user"], deleted_at=100)
    assert await repo.list_raw_event_ids_by_chat_message(
        user_id="owner", session_id="room-a", message_id="same-platform-message-id",
    ) == ["selected"]
    with pytest.raises(ValueError, match="must not be empty"):
        await repo.list_raw_event_ids_by_chat_message(user_id="owner", session_id="", message_id="id")


async def test_raw_message_retirement_preserves_session_ownership(repository):
    await assert_exact_message_retirement_scope(repository[0])
