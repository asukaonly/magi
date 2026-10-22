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


async def test_embedding_publication_is_atomic_and_stale_sources_are_rejected(mysql_environment):
    from .test_event_repository import embedding_publication

    repo, database = mysql_environment
    await repo.append(command("source"))
    publication = await embedding_publication(repo, "source")
    invalid = replace(publication, chunks=(publication.chunks[0], publication.chunks[0]))
    with pytest.raises(PersistenceConflictError):
        await repo.publish_event_embeddings([invalid])
    assert await repo.fetch_embedding_chunks(["source::chunk-0"]) == []
    assert (await repo.get("source")).event.embedding_status == "pending"
    async with database.transaction() as connection:
        assert (
            await connection.execute(select(func.count()).select_from(s.profiles))
        ).scalar_one() == 0
    assert await repo.publish_event_embeddings([publication]) == {"source"}
    assert (await repo.get("source")).last_embedded_at == 123
    assert await repo.visible_embedding_chunk_ids(["source::chunk-0", "missing"]) == {
        "source::chunk-0"
    }
    async with database.transaction() as connection:
        await connection.execute(
            update(s.events).where(s.events.c.event_id == "source").values(content="changed source")
        )
    assert await repo.publish_event_embeddings([publication]) == set()
    assert await repo.remove_event_embedding_chunks([publication.source]) == []
    current = await embedding_publication(repo, "source")
    assert await repo.publish_event_embeddings([current]) == {"source"}
    assert await repo.remove_event_embedding_chunks([current.source]) == ["source::chunk-0"]
    assert (await repo.get("source")).event.embedding_status == "skipped"


async def test_deleted_or_control_sources_cannot_hydrate_vector_hits(mysql_environment):
    from .test_event_repository import embedding_publication
    from magi.memory.event_contracts import MemoryDomain

    repo, database = mysql_environment
    await repo.append(command("source"))
    publication = await embedding_publication(repo, "source")
    await repo.publish_event_embeddings([publication])
    async with database.transaction() as connection:
        await connection.execute(
            update(s.events).values(memory_domain=int(MemoryDomain.SYSTEM_CONTROL))
        )
    assert await repo.visible_embedding_chunk_ids(["source::chunk-0"]) == set()
    async with database.transaction() as connection:
        await connection.execute(update(s.events).values(deleted_at=100))
    assert await repo.publish_event_embeddings([publication]) == set()
    assert await repo.fetch_embedding_chunks(["source::chunk-0"]) == []
    assert await repo.count_pending_embeddings() == 0


async def test_cognition_handoffs_survive_restart_and_retire_independently(mysql_environment):
    repo, database = mysql_environment
    value = command("cognition")
    value.event.cognition_eligible = True
    await repo.append(value)
    ordinary = command("ordinary")
    ordinary.event.cognition_eligible = False
    await repo.append(ordinary)
    assert await repo.list_ready_cognition_handoffs(now=100) == ["cognition"]
    await repo.retry_cognition_handoff("cognition", error="provider failed", now=100)
    restarted = MysqlMemoryEventRepository(database, center_id="center-test")
    await restarted.initialize()
    assert await restarted.list_ready_cognition_handoffs(now=100) == []
    assert await restarted.list_ready_cognition_handoffs(now=101) == ["cognition"]
    assert await restarted.get_pinned_payloads(["cognition", "ordinary", "missing"]) == {
        "cognition": "capture-time full content",
        "ordinary": "capture-time full content",
    }
    await restarted.complete_cognition_handoff("cognition")
    assert await restarted.list_ready_cognition_handoffs(now=1000) == []
    assert (
        await restarted.prune_pinned_payloads(retention_seconds=0, now=value.event.created_at + 100)
        == 2
    )
    assert await restarted.get_pinned_payloads(["cognition"]) == {}
    assert await restarted.get("cognition") is not None


async def test_clear_failure_rolls_back_every_owned_table_and_fence(mysql_environment):
    from magi.core.persistence_errors import PersistenceUnavailableError
    from .test_event_repository import embedding_publication

    repo, database = mysql_environment
    value = command("source")
    value.event.cognition_eligible = True
    await repo.append(value)
    publication = await embedding_publication(repo, "source")
    await repo.publish_event_embeddings([publication])
    async with database.transaction() as connection:
        await connection.execute(text("CREATE TABLE unrelated_owner (value INTEGER)"))
        await connection.execute(text("INSERT INTO unrelated_owner VALUES (7)"))
        await connection.execute(
            text(
                "CREATE TRIGGER reject_clear BEFORE DELETE ON magi_l1_events FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='clear interrupted'"
            )
        )
    with pytest.raises(PersistenceUnavailableError):
        await repo.clear_events(entity_link_clear_generation=1)
    assert set((await table_counts(database)).values()) == {1}
    assert (await repo.get_clear_state()).entity_link_generation == 0
    assert await repo.visible_embedding_chunk_ids(["source::chunk-0"]) == {"source::chunk-0"}
    assert await repo.list_ready_cognition_handoffs(now=100) == ["source"]
    async with database.transaction() as connection:
        await connection.execute(text("DROP TRIGGER reject_clear"))
    highwater = await repo.event_scan_high_water()
    assert await repo.clear_events(entity_link_clear_generation=1) == 1
    assert (await repo.get_clear_state()).entity_link_generation == 1
    assert set((await table_counts(database)).values()) == {0}
    assert await repo.list_ready_cognition_handoffs(now=100) == []
    assert await repo.publish_event_embeddings([publication]) == set()
    async with database.transaction() as connection:
        assert (
            await connection.execute(text("SELECT value FROM unrelated_owner"))
        ).scalar_one() == 7
        assert (await connection.execute(select(s.state.c.center_id))).scalar_one() == "center-test"
    await repo.append(command("after-clear"))
    assert (await repo.get("after-clear")).event.id > highwater


async def test_evidence_scan_rejects_changed_deleted_and_invalid_records(mysql_environment):
    from magi.memory.l1.maintenance_contracts import EvidenceAnnotationUpdate, EvidenceBackfillQuery

    repo, database = mysql_environment
    for name in ("valid", "changed", "deleted", "invalid"):
        await repo.append(command(name))
    async with database.transaction() as connection:
        await connection.execute(
            update(s.events).where(s.events.c.event_id == "invalid").values(metadata_json="[]")
        )
    query = EvidenceBackfillQuery()
    highwater = await repo.event_scan_high_water()
    page = await repo.scan_evidence_backfill(query, after=0, through=highwater, limit=10)
    assert len(page) == 4
    assert page[-1].record is None
    assert "metadata must be an object" in page[-1].error
    updates = [
        EvidenceAnnotationUpdate(item.record, replace(item.record.evidence, rule_version=99))
        for item in page
        if item.record is not None
    ]
    async with database.transaction() as connection:
        await connection.execute(
            update(s.events).where(s.events.c.event_id == "changed").values(content="new text")
        )
        await connection.execute(
            update(s.events).where(s.events.c.event_id == "deleted").values(deleted_at=100)
        )
    assert await repo.apply_evidence_annotations(updates) == 1
    assert (await repo.get("valid")).evidence.rule_version == 99
    assert (await repo.get("changed")).evidence.rule_version == 1
    assert (await repo.get("deleted")).evidence.rule_version == 1
    assert (
        await repo.count_evidence_backfill(
            EvidenceBackfillQuery(stale_rule_version=99), through=highwater
        )
        == 2
    )
    await repo.append(command("later"))
    assert (
        await repo.scan_evidence_backfill(
            query, after=page[-1].sequence, through=highwater, limit=10
        )
        == []
    )


async def test_embedding_rebuild_retention_source_summary_and_preview(mysql_environment):
    repo, database = mysql_environment
    from magi.memory.event_contracts import RetentionClass

    for i in range(3):
        value = command(f"event-{i}")
        value.event.timestamp = i + 10
        value.event.retention_class = RetentionClass.COMPRESSIBLE
        await repo.append(value)
    assert await repo.count_pending_embeddings() == 3
    highwater = await repo.event_scan_high_water()
    page = await repo.embedding_rebuild_page(after=0, through=highwater, limit=2)
    assert [event.event_id for _, event in page] == ["event-0", "event-1"]
    assert [
        event.event_id
        for _, event in await repo.embedding_rebuild_page(
            after=page[-1][0], through=highwater, limit=2
        )
    ] == ["event-2"]
    assert (await repo.summarize_event_sources())[0]["event_count"] == 3
    assert await repo.list_compressible_event_page(older_than=20, after=(10, "event-0")) == [
        (11, "event-1"),
        (12, "event-2"),
    ]
    async with database.transaction() as connection:
        await connection.execute(
            update(s.events).where(s.events.c.event_id == "event-2").values(deleted_at=100)
        )
    await repo.rebuild_chat_session_projection("session")
    async with database.transaction() as connection:
        row = (await connection.execute(select(s.sessions))).mappings().one()
        assert row["message_count"] == 2
        assert row["last_message_at"] == 11
    await repo.retire_chat_session_projection("session", deleted_at=101)
    async with database.transaction() as connection:
        row = (await connection.execute(select(s.sessions))).mappings().one()
        assert row["message_count"] == 0
        assert row["last_message_preview"] == ""
        assert row["deleted_at"] == 101


async def test_entity_projection_revision_conflict_rolls_back_whole_batch(mysql_environment):
    repo, _ = mysql_environment
    for name in ("first", "second"):
        await repo.append(command(name))
    assert await repo.write_event_entities([("first", "manual", "topic", 0.4)]) == 1
    assert await repo.write_event_entities([("first", "manual", "person", 0.9)]) == 0
    assert await repo.replace_projected_event_entities_batch(
        projections=[
            ("first", 1, "lease-a", 1, 0, [("derived", "topic", 0.8), ("manual", "topic", 0.9)]),
            ("second", 1, "lease-b", 1, 0, [("derived", "topic", 0.7)]),
        ]
    )
    assert sorted(await repo.resolve_event_entities(["first"])) == ["derived", "manual"]
    assert await repo.expand_by_entities(["first"]) == ["second"]
    assert await repo.find_events_by_entities(["derived", "manual"]) == [
        ("first", 2),
        ("second", 1),
    ]
    assert (await repo.get_entity_event_ids(["manual"]))["manual"] == ["first"]
    with pytest.raises(RuntimeError, match="conflicting"):
        await repo.replace_projected_event_entities_batch(
            projections=[
                ("first", 2, "new", 1, 0, []),
                ("second", 1, "wrong-lease", 1, 0, []),
            ]
        )
    assert sorted(await repo.resolve_event_entities(["first"])) == ["derived", "manual"]
    assert await repo.replace_projected_event_entities_batch(
        projections=[("first", 2, "new", 1, 0, [])]
    )
    assert await repo.resolve_event_entities(["first"]) == ["manual"]
    assert await repo.replace_projected_event_entities_batch(
        projections=[("first", 1, "obsolete", 9, 0, [("old", None, None)])]
    )
    assert await repo.resolve_event_entities(["first"]) == ["manual"]


async def test_entity_generation_is_durable_and_manual_links_survive_alignment(mysql_environment):
    repo, database = mysql_environment
    await repo.append(command("source"))
    await repo.write_event_entities([("source", "manual", None, None)])
    await repo.replace_projected_event_entities_batch(
        projections=[("source", 1, "lease", 1, 0, [("derived", None, None)])]
    )
    with pytest.raises(RuntimeError, match="requires unified"):
        await repo.clear_events()
    assert await repo.align_entity_link_projection_clear_generation(1) == 1
    assert await repo.align_entity_link_projection_clear_generation(1) == 0
    restarted = MysqlMemoryEventRepository(database, center_id="center-test")
    await restarted.initialize()
    assert not await restarted.replace_projected_event_entities_batch(
        projections=[("source", 2, "old", 1, 0, [("old", None, None)])]
    )
    assert await restarted.resolve_event_entities(["source"]) == ["manual"]
    with pytest.raises(RuntimeError, match="backwards"):
        await restarted.align_entity_link_projection_clear_generation(0)
    await restarted.clear_events(entity_link_clear_generation=2)
    assert await repo.resolve_event_entities(["source"]) == []
    assert not await repo.replace_projected_event_entities_batch(
        projections=[("source", 3, "old", 1, 1, [("old", None, None)])]
    )


async def test_purge_retains_live_events_and_their_side_records(mysql_environment):
    from .test_event_repository import embedding_publication

    repo, _ = mysql_environment
    for name in ("retired", "live"):
        await repo.append(command(name, key=name))
        await repo.publish_event_embeddings([await embedding_publication(repo, name)])
        await repo.write_event_entities([(name, "entity", None, 0.5)])
    assert await repo.soft_delete_events(["retired"], deleted_at=100) == 1
    assert await repo.soft_delete_events(["retired"], deleted_at=200) == 0
    assert (await repo.get("retired")).deleted_at == 100
    plan = await repo.prepare_event_deletion(["retired", "live", "missing"], only_deleted=True)
    assert plan.event_ids == ("retired",)
    assert plan.chunk_ids == ()
    assert await repo.list_active_event_ids_by_entity("entity") == ["live"]
    assert await repo.list_raw_event_ids_by_entity("entity") == ["live", "retired"]
    assert await repo.purge_deleted_events(["retired", "live", "missing"]) == 1
    assert await repo.get("retired") is None
    assert await repo.visible_embedding_chunk_ids(["live::chunk-0"]) == {"live::chunk-0"}
    assert await repo.get_pinned_payloads(["live"]) == {"live": "capture-time full content"}
    assert await repo.resolve_event_entities(["live"]) == ["entity"]
    assert "retired" not in await repo.list_ready_cognition_handoffs(now=1000)


async def test_deletion_selectors_keep_owner_time_and_message_boundaries(mysql_environment):
    repo, _ = mysql_environment
    for name, user, session, turn, message, stamp in [
        ("a", "owner", "session", "turn", "message", 10),
        ("b", "other", "session", "turn", "message", 11),
        ("c", "owner", "another", "another-turn", "another-message", 12),
        ("d", None, "session", "turn", "message", 13),
    ]:
        value = command(name)
        value.event.user_id, value.event.session_id, value.event.turn_id = user, session, turn
        value.event.source_item_id, value.event.timestamp = message, stamp
        await repo.append(value)
    assert await repo.list_active_event_ids_by_chat_sources(
        user_id="owner", session_id="session"
    ) == ["a", "d"]
    assert await repo.list_raw_event_ids_by_chat_sources(
        user_id="owner", turn_ids=["another-turn"], include_session=False
    ) == ["c"]
    assert await repo.list_active_event_ids_by_chat_message(
        user_id="owner", session_id="session", message_id="message"
    ) == ["a", "d"]
    assert await repo.filter_ids_by_user(["d", "c", "b", "a"], "owner") == ["c", "a"]
    assert await repo.list_active_event_ids_by_time_range(start=10, end=13, limit=2) == ["a", "b"]
    assert await repo.list_active_event_ids_by_time_range(start=10, end=13, after_event_id="b") == [
        "c",
        "d",
    ]
    await repo.soft_delete_events(["a"], deleted_at=100)
    assert await repo.list_active_event_ids_by_chat_sources(
        user_id="owner", session_id="session"
    ) == ["d"]
    assert await repo.list_raw_event_ids_by_chat_sources(user_id="owner", session_id="session") == [
        "a",
        "d",
    ]
    assert await repo.list_raw_event_ids_by_chat_message(
        user_id="owner", session_id="session", message_id="message"
    ) == ["a", "d"]
    with pytest.raises(ValueError, match="finite"):
        await repo.list_raw_event_ids_by_time_range(start=0, end=float("inf"))


async def test_facet_queries_and_rebuild_use_current_source_records(mysql_environment):
    from magi.memory.l1.source_facets import SourceFacet
    from sqlalchemy import delete

    repo, database = mysql_environment
    value = command("source")
    value.event.timestamp = 10
    value = replace(
        value,
        metadata={"source_facets": [{"name": "topic", "text": "Jazz"}]},
        source_facets=(
            SourceFacet("source", "chat", "topic", text_value="Jazz", normalized_text_value="jazz"),
        ),
    )
    await repo.append(value)
    assert (await repo.list_source_facets(event_id="source"))[0].normalized_text_value == "jazz"
    assert await repo.count_source_facets(source="chat", facet_names=["topic"]) == 1
    query = dict(
        source="chat",
        facet_names=["topic"],
        normalized_text_values=["jazz"],
        user_id="local_user",
        time_start=10,
        time_end=10,
    )
    assert [row.event.event_id for row in await repo.find_events_by_source_facets(**query)] == [
        "source"
    ]
    assert await repo.find_events_by_source_facets(**{**query, "user_id": "other"}) == []
    async with database.transaction() as connection:
        await connection.execute(delete(s.facets))
    assert await repo.rebuild_source_facets(batch_size=1) == {"processed": 1, "indexed": 1}
    assert [row.event.event_id for row in await repo.find_events_by_source_facets(**query)] == [
        "source"
    ]
    assert await repo.rebuild_source_facets(limit=0) == {"processed": 0, "indexed": 0}
    await repo.soft_delete_events(["source"], deleted_at=100)
    assert await repo.find_events_by_source_facets(**query) == []
    assert await repo.rebuild_source_facets() == {"processed": 0, "indexed": 0}
    await repo.purge_deleted_events(["source"])
    assert await repo.count_source_facets() == 0


async def test_lexical_search_filters_source_and_treats_query_as_text(mysql_environment):
    repo, database = mysql_environment
    for name, content, user in [
        ("chinese", "喜欢爵士乐，打开卧室灯", "local_user"),
        ("english", "A crow enjoys jazz music", "local_user"),
        ("other", "A crowded city enjoys music", "other"),
    ]:
        value = command(name)
        value.event.content, value.event.user_id, value.event.timestamp = content, user, 10
        await repo.append(replace(value, search_text=content))
    assert [key for key, _ in await repo.bm25_search("卧室灯")] == ["chinese"]
    assert [key for key, _ in await repo.bm25_search("crow", strict=True)] == ["english"]
    assert [
        key for key, _ in await repo.bm25_search('"jazz" +music -unknown', user_id="local_user")
    ] == ["english"]
    assert await repo.bm25_search("爵士乐", user_id="other") == []
    assert await repo.bm25_search("爵士乐", start_time=11) == []
    assert await repo.bm25_search("爵士乐", l1_retrieval_scopes=[]) == []
    assert await repo.bm25_search('"+*() --') == []
    assert all(score <= 0 for _, score in await repo.bm25_search("music"))
    async with database.transaction() as connection:
        await connection.execute(
            update(s.events).where(s.events.c.event_id == "chinese").values(search_text="")
        )
    assert await repo.backfill_fts(batch_size=1) == 1
    assert await repo.backfill_fts() == 0
    assert [key for key, _ in await repo.bm25_search("卧室灯")] == ["chinese"]
    await repo.soft_delete_events(["chinese"], deleted_at=100)
    assert await repo.bm25_search("卧室灯") == []


async def test_mysql_l1_service_with_real_chroma_survives_restart_and_clear(
    mysql_environment, tmp_path, ensure_db_schema
):
    from magi.memory.l1.event_store import L1EventStore
    from memory.test_vector_factory import _chroma_factory
    from memory.test_clear_embedding_barrier import _DeterministicEmbeddingService, _user_message

    repo, database = mysql_environment
    factory = _chroma_factory(tmp_path, ensure_db_schema)
    store = L1EventStore(
        event_repository=repo,
        vector_index_factory=factory,
        embedding_service=_DeterministicEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    try:
        await store.store(_user_message(event_id="travel", content="Travel preference."))
        assert [row["event_id"] for row in await store.search_events(query="Travel")] == ["travel"]
        assert await store.rebuild_embeddings(batch_size=1) == 1
        await store.shutdown()
        await factory.close()
        factory = _chroma_factory(tmp_path, ensure_db_schema)
        restarted = MysqlMemoryEventRepository(database, center_id="center-test")
        store = L1EventStore(
            event_repository=restarted,
            vector_index_factory=factory,
            embedding_service=_DeterministicEmbeddingService(),
            async_embeddings=False,
        )
        await store.initialize()
        hits = await store.vector_search(query="Travel")
        assert hits
        assert [row["event_id"] for row in await store.search_events(query="Travel")] == ["travel"]
        await store.clear(restart_workers=False)
        await factory.create("l1").upsert(
            entity_id=hits[0].entity_id, embedding=_DeterministicEmbeddingService._result("Travel")
        )
        assert await store.vector_search(query="Travel")
        assert await store.search_events(query="Travel") == []
        assert await store.rebuild_embeddings(batch_size=1) == 0
        assert await store.vector_search(query="Travel") == []
        assert await restarted.list_ready_cognition_handoffs(now=1e20) == []
    finally:
        await store.shutdown()
        await factory.clear_all()
        await factory.close()


def test_mysql_event_adapter_implements_the_complete_repository_contract():
    import inspect
    from magi.memory.l1.ports import MemoryEventRepository

    expected = {
        name
        for name, method in inspect.getmembers(MemoryEventRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    assert not expected.difference(dir(MysqlMemoryEventRepository))


async def test_raw_message_retirement_preserves_session_ownership(mysql_environment):
    from .test_event_repository import assert_exact_message_retirement_scope

    await assert_exact_message_retirement_scope(mysql_environment[0])


async def test_event_sequence_survives_clear_and_rolls_back_with_failed_append(
    mysql_environment, monkeypatch
):
    repo, database = mysql_environment
    await repo.append(command("before"))
    before = (await repo.get("before")).event.id
    await repo.clear_events()
    original = repo._append_side_rows

    async def failed(*args):
        await original(*args)
        raise RuntimeError("interrupted transaction")

    monkeypatch.setattr(repo, "_append_side_rows", failed)
    with pytest.raises(RuntimeError, match="interrupted"):
        await repo.append(command("failed"))
    async with database.transaction() as connection:
        assert (await connection.execute(select(s.state.c.event_sequence))).scalar_one() == before
    monkeypatch.setattr(repo, "_append_side_rows", original)
    await repo.append(command("after"))
    assert (await repo.get("after")).event.id == before + 1
