"""Atomic chat behavior against an isolated real MySQL database."""

import asyncio
import os
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from magi_plugin_sdk.delivery import DeliveryContent
from magi_plugin_sdk.endpoints import EndpointRef

from magi.chat.contracts import ChatMessageRecord
from magi.chat.errors import ChatTurnConflictError
from magi.chat.model_context import ModelContextItem, ModelContextRevisionConflictError
from magi.chat.storage.mysql.repository import MysqlChatRepository
from magi.chat.storage.outbound_delivery import insert_outbound_deliveries
from magi.core.persistence_errors import PersistenceConflictError
from magi.db.mysql import MysqlDatabase, MysqlSettings
from magi.db.mysql_migrations import upgrade_mysql_chat
from magi.delivery.routing import DeliveryPlan
from magi.utils.runtime import RuntimePaths


@pytest.fixture
async def mysql_chat(monkeypatch, tmp_path):
    port = os.environ.get("MAGI_TEST_MYSQL_PORT")
    if not port:
        pytest.skip("Set MAGI_TEST_MYSQL_PORT for native MySQL chat contracts")
    monkeypatch.setenv("MAGI_MYSQL_CHAT_PASSWORD", os.environ.get("MAGI_TEST_MYSQL_PASSWORD", ""))
    settings = MysqlSettings(host="127.0.0.1", port=int(port), database="magi_test_architecture",
        user=os.environ.get("MAGI_TEST_MYSQL_USER", "root"), password_env="MAGI_MYSQL_CHAT_PASSWORD", tls=False)
    admin = MysqlDatabase(settings)
    name = "magi_test_chat_" + uuid4().hex
    async with admin.transaction() as connection:
        await connection.execute(text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"))
    database = MysqlDatabase(settings.model_copy(update={"database": name}))
    paths = RuntimePaths(base_dir=tmp_path)
    try:
        await upgrade_mysql_chat(database)
        store = MysqlChatRepository(database, center_id="center-test", runtime_paths=paths)
        await store.initialize()
        yield store, database, paths
    finally:
        await database.close()
        async with admin.transaction() as connection:
            await connection.execute(text(f"DROP DATABASE {name}"))
        await admin.close()


async def create_turn(store, *, turn="t1", session="s1"):
    return await store.create_user_turn_once(session_id=session, user_id="u1", turn_id=turn,
        message_text="Turn on the living room light", created_at_ms=100,
        runtime_envelope={"session_id": session, "turn_id": turn, "message": "light", "attachments": [], "metadata": {}},
        request_fingerprint="fingerprint-"+turn)


async def test_native_schema_owner_and_concurrent_acceptance(mysql_chat):
    store, database, paths = mysql_chat
    results = await asyncio.gather(*(create_turn(store) for _ in range(8)))
    assert sum(value.created for value in results) == 1
    async with store.database.session() as connection:
        assert (await connection.execute_fetchall("SELECT COUNT(*) FROM chat_messages"))[0][0] == 1
    with pytest.raises(ChatTurnConflictError, match="existing session identifier"):
        await create_turn(store, session="S1", turn="t2")
    alien = MysqlChatRepository(database, center_id="other", runtime_paths=paths)
    with pytest.raises(PersistenceConflictError, match="another center"):
        await alien.initialize()
    assert not paths.chat_db_path.exists()


async def test_native_model_context_cas_and_budget(mysql_chat):
    store, database, paths = mysql_chat
    await create_turn(store)
    item = ModelContextItem.from_prompt_message({"role": "user", "content": "hello"}, source="test")
    saved = await store.append_model_context(session_id="s1", items=(item,), expected_revision=0)
    assert saved.revision == 1
    with pytest.raises(ModelContextRevisionConflictError):
        await store.append_model_context(session_id="s1", items=(item,), expected_revision=0)
    reopened = MysqlChatRepository(database, center_id="center-test", runtime_paths=paths)
    assert await reopened.load_model_context(session_id="s1") == saved
    await store.ensure_task_execution_budget(root_turn_id="t1", max_llm_calls=3, max_worker_launches=2)
    claims = await asyncio.gather(*(store.reserve_task_execution_budget(root_turn_id="t1", resource="llm_calls", count=1, max_llm_calls=3, max_worker_launches=2) for _ in range(8)))
    assert sum(item[0] for item in claims) == 3


@pytest.mark.parametrize("wrong_owner", [False, True])
async def test_native_outcome_projection_and_targets_are_atomic(mysql_chat, wrong_owner):
    store, _, _ = mysql_chat
    await create_turn(store)
    message = ChatMessageRecord("m2", "s1", "t1", "u1", "assistant", "assistant_final", "Light is on", "{}",
        True, True, 201, 2, None, None)
    plan = DeliveryPlan("s1", "u1", (EndpointRef("phone", "text", "owner"), EndpointRef("home", "audio", "speaker")))
    async def commit():
        return await store.commit_unmanaged_assistant_outcome(post_turn_source="conversation", turn_id="t1", messages=[message],
            attachment_payloads_by_message_id={}, trace_id=None, execution_mode="direct_llm", ux_plan={},
            response_mode="final_only", started_at_ms=100, completed_at_ms=201,
            delivery_plan=replace(plan, user_id="another") if wrong_owner else plan)
    if wrong_owner:
        with pytest.raises(ValueError, match="owner"):
            await commit()
        assert await store.list_outbound_deliveries(message_id="m2") == []
    else:
        assert await commit()
        assert len(await store.list_outbound_deliveries(message_id="m2")) == 2
        async with store.database.session() as connection:
            rows = await connection.execute_fetchall("SELECT source_message_ids FROM chat_post_turn_outcomes")
            assert len(rows) == 1 and "m2" in rows[0][0]


async def test_native_redaction_cancels_delivery_and_post_turn_intents(mysql_chat):
    store, _, _ = mysql_chat
    await create_turn(store)
    async with store.database.session() as connection:
        await connection.execute("INSERT INTO chat_messages(message_id,session_id,user_id,role,message_kind,content_text,created_at_ms,sequence_no) VALUES ('m2','s1','u1','assistant','assistant_final','hello',200,2)")
        await insert_outbound_deliveries(connection, content=DeliveryContent("hello", message_id="m2"),
            plan=DeliveryPlan("s1", "u1", (EndpointRef("home", "audio", "speaker"),)), now_ms=201)
        await connection.commit()
    old = await store.claim_outbound_delivery(now_ms=202)
    assert await store.begin_outbound_attempt(old, retry_safe=False, now_ms=203)
    async with store.database.session() as connection:
        await connection.execute("UPDATE chat_messages SET is_visible=0 WHERE message_id='m2'")
        await connection.commit()
    saved, = await store.list_outbound_deliveries(message_id="m2")
    assert saved.state == "uncertain" and not saved.content.text
    assert not await store.settle_outbound_delivery(old, state="failed", now_ms=204)


async def test_native_batch_revocation_releases_surviving_members(mysql_chat):
    store, _, _ = mysql_chat
    for turn in ("t1", "t2"):
        await create_turn(store, turn=turn)
        message = ChatMessageRecord("reply-"+turn, "s1", turn, "u1", "assistant", "assistant_final", "Done", "{}",
            True, True, 201, 2, None, None)
        await store.commit_unmanaged_assistant_outcome(post_turn_source="conversation", turn_id=turn, messages=[message],
            attachment_payloads_by_message_id={}, trace_id=None, execution_mode="direct_llm", ux_plan={},
            response_mode="final_only", started_at_ms=100, completed_at_ms=201)
    outcomes = await store.list_ready_post_turn_outcomes()
    assert len(outcomes) == 2
    lease = await store.claim_post_turn_batch(tuple(row["outcome_id"] for row in outcomes))
    assert lease is not None
    await store.save_post_turn_analysis(lease, {"effect": "sample"})
    await store.settle_post_turn_effect(lease, "memory")
    async with store.database.session() as connection:
        await connection.execute("UPDATE chat_messages SET is_visible=0 WHERE message_id='reply-t1'")
        await connection.commit()
    assert not await store.finish_post_turn_batch(lease)
    remaining = await store.list_ready_post_turn_outcomes()
    assert len(remaining) == 1 and remaining[0]["source_turn_id"] == "t2"
    new_lease = await store.claim_post_turn_batch((remaining[0]["outcome_id"],))
    assert new_lease is not None
    assert await store.finish_post_turn_batch(new_lease)


async def test_native_opaque_identities_and_dedup_are_lossless(mysql_chat):
    store, _, _ = mysql_chat
    session = "主题" * 900
    turn = "用户消息" * 600
    await create_turn(store, turn=turn, session=session)
    assert not (await create_turn(store, turn=turn, session=session)).created
    assert await store.is_session_available(user_id="u1", session_id=session)
    await create_turn(store, turn="unicode-upper", session="Ä")
    await create_turn(store, turn="unicode-lower", session="ä")
    assert await store.is_session_available(user_id="u1", session_id="Ä")
    assert await store.is_session_available(user_id="u1", session_id="ä")


@pytest.mark.parametrize("interruption", ["failure", "cancel"])
async def test_native_side_effect_failure_rolls_back_acceptance(mysql_chat, monkeypatch, interruption):
    store, _, _ = mysql_chat
    ready = asyncio.Event()
    original = store._upsert_session_with_connection
    async def fail(connection, record):
        await original(connection, record)
        ready.set()
        if interruption == "failure":
            raise RuntimeError("Injected transaction failure")
        await asyncio.Event().wait()
    monkeypatch.setattr(store, "_upsert_session_with_connection", fail)
    task = asyncio.create_task(create_turn(store))
    await asyncio.wait_for(ready.wait(), 10)
    if interruption == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="Injected"):
            await task
    assert await store.is_empty()
    monkeypatch.setattr(store, "_upsert_session_with_connection", original)
    assert (await create_turn(store)).created


async def test_native_clear_fence_rejects_stale_writes_and_unowned_claims(mysql_chat):
    store, database, paths = mysql_chat
    await create_turn(store)
    async with store.database.session() as connection:
        await connection.execute("INSERT INTO chat_cleared_session_scopes(session_id,cleared_at_ms) VALUES ('s1',201)")
        await connection.commit()
    with pytest.raises((ChatTurnConflictError, PersistenceConflictError)):
        await create_turn(store, turn="late")
    async with database.transaction() as connection:
        await connection.execute(text("DELETE FROM magi_chat_owner"))
    new = MysqlChatRepository(database, center_id="other", runtime_paths=paths)
    with pytest.raises(PersistenceConflictError, match="already contains data"):
        await new.initialize()


_PORT_CONTRACTS = [
    ("test_model_context_store", name, "tmp_path") for name in (
        "test_append_and_load_model_context",
        "test_boundary_reconstructs_immutable_model_call",
        "test_visible_outcome_atomically_promotes_working_context",
        "test_cancellation_promotes_runtime_outcome_without_draft",
        "test_model_context_revision_conflict_is_rejected",
    )
] + [
    ("test_task_execution_budgets", name, "chat_db_path") for name in (
        "test_budget_survives_store_restart_and_preserves_original_limits",
        "test_concurrent_admissions_cannot_oversell_durable_budget",
        "test_concurrent_worker_admissions_cannot_oversell_durable_budget",
        "test_independent_store_instances_serialize_reserve_and_refund",
        "test_unused_prepaid_capacity_is_released_durably",
    )
] + [
    ("test_assistant_memory_projection", name, "runtime_paths_with_schema") for name in (
        "test_assistant_outcome_allows_explicit_no_message_completion",
        "test_outbox_lease_expiry_and_completion_are_owner_scoped",
    )
]


@pytest.mark.parametrize("module_name,scenario,argument", _PORT_CONTRACTS, ids=[item[1] for item in _PORT_CONTRACTS])
async def test_existing_write_port_contracts_on_mysql(mysql_chat, monkeypatch, tmp_path, module_name, scenario, argument):
    """Reuse storage-independent assertions with a real native repository factory."""
    import importlib
    module = importlib.import_module(module_name)
    _, database, paths = mysql_chat
    def repository_factory(*, db_path):
        return MysqlChatRepository(database, center_id="center-test", runtime_paths=paths)
    monkeypatch.setattr(module, "ChatStore", repository_factory)
    value = paths if argument == "runtime_paths_with_schema" else tmp_path / "unused.db" if argument == "chat_db_path" else tmp_path
    await getattr(module, scenario)(**{argument: value})
    assert not paths.chat_db_path.exists()


async def test_native_session_requires_explicit_commit(mysql_chat):
    store, _, _ = mysql_chat
    async with store.database.session() as connection:
        await connection.execute("INSERT INTO chat_sessions(session_id,user_id,title,created_at_ms,updated_at_ms) VALUES ('uncommitted','u1','title',1,1)")
    assert await store.is_empty()


async def test_native_schema_keys_do_not_escape_domain_rows(mysql_chat):
    store, _, _ = mysql_chat
    await create_turn(store)
    async with store.database.session() as connection:
        rows = await connection.execute_fetchall("SELECT * FROM chat_sessions")
    assert rows[0]["session_id"] == "s1"
    assert not any(key.startswith("__") for key in dict(rows[0]))


@pytest.fixture
async def mysql_chat_reader(mysql_chat, monkeypatch):
    from magi.chat.storage.mysql.read_database import MysqlChatReadDatabase
    from magi.chat.storage.relational_reader import RelationalChatReadRepository
    from magi.chat.storage.workspace_preferences import JsonRecentWorkspaceRepository
    from magi.runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
    from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService
    from _shared.db_schema import apply_chain_schema
    _, database, paths = mysql_chat
    settings = MysqlSettings(host="127.0.0.1", port=int(os.environ["MAGI_TEST_MYSQL_PORT"]),
        database=database._engine.url.database, user=os.environ.get("MAGI_TEST_MYSQL_USER", "root"),
        password_env="MAGI_MYSQL_CHAT_PASSWORD", tls=False)
    reads = MysqlChatReadDatabase(settings, center_id="center-test")
    apply_chain_schema("runtime_trace", paths.runtime_trace_db_path)
    trace = ChatTraceReadService()
    trace._runtime_trace_db_path = paths.runtime_trace_db_path
    monkeypatch.setattr("magi.chat.storage.relational_reader.get_chat_trace_read_service", lambda: trace)
    reader = RelationalChatReadRepository(database=reads, runtime_paths=paths,
        trace_content=SqliteTraceContentRepository(paths.runtime_trace_db_path),
        workspace_preferences=JsonRecentWorkspaceRepository(paths.config_dir / "recent_chat_workspaces.json"))
    try:
        yield reader
    finally:
        reader.close()
        reads.close()


async def test_native_reader_session_pages_and_revision_invalidation(mysql_chat, mysql_chat_reader):
    from magi.core.chat_read_models import StalePageCursor
    reader = mysql_chat_reader
    sessions = await asyncio.gather(*(reader.acreate_new_session("u1", idempotency_key=f"request-{n}") for n in range(3)))
    assert len(set(sessions)) == 3
    assert await reader.acreate_new_session("u1", idempotency_key="request-0") == sessions[0]
    page = await reader.alist_session_page("u1", limit=2)
    assert page["has_more"] and page["count"] == 2
    assert (await reader.alist_session_page("u1", limit=2, before=page["next_before"]))["count"] == 1
    await reader.arename_session("u1", sessions[0], "New title")
    assert (await reader.aget_session_summary("u1", sessions[0])).title == "New title"
    with pytest.raises(StalePageCursor):
        await reader.alist_session_page("u1", limit=2, before=page["next_before"])
    assert not mysql_chat[2].chat_db_path.exists()


async def test_native_reader_history_clear_and_restart_barrier(mysql_chat, mysql_chat_reader):
    store, _, _ = mysql_chat
    reader = mysql_chat_reader
    await create_turn(store)
    page = await reader.aget_history_page("u1", "s1", limit=10)
    assert page["count"] == 1
    await reader.aclear_conversation_history("u1", "s1")
    assert (await reader.aget_history_page("u1", "s1", limit=10))["count"] == 0
    with pytest.raises((ChatTurnConflictError, PersistenceConflictError)):
        await create_turn(store)
    assert (await create_turn(store, turn="new-turn")).created


async def test_native_reader_full_clear_keeps_fence_until_completion(mysql_chat, mysql_chat_reader):
    store, _, paths = mysql_chat
    reader = mysql_chat_reader
    await create_turn(store)
    assert await reader.aclear_all_sessions() == 1
    assert reader.get_interrupted_global_clear_count() == 1
    with pytest.raises((ChatTurnConflictError, PersistenceConflictError)):
        await create_turn(store, turn="late", session="other")
    assert await reader.acomplete_global_clear()
    with pytest.raises(ChatTurnConflictError, match="permanently cleared"):
        await create_turn(store)
    assert await reader.alist_sessions("u1") == []
    assert (await create_turn(store, turn="new", session="new")).created
    assert not paths.chat_db_path.exists()


async def test_native_reader_cleanup_failure_reopens_exact_asset_receipt(mysql_chat, mysql_chat_reader, monkeypatch):
    from magi.chat.asset_gc import ChatAssetDeletionError
    from magi.core.chat_cleanup import ChatSurfaceCleanupPendingError
    store, _, paths = mysql_chat
    reader = mysql_chat_reader
    asset = paths.chat_files_dir / "s1" / "t1" / "attachment1__private.txt"
    asset.parent.mkdir(parents=True)
    asset.write_text("private attachment", encoding="utf-8")
    accepted = await store.create_user_turn_once(session_id="s1", user_id="u1", turn_id="t1",
        message_text="private transcript", created_at_ms=100, attachment_payloads=[{
            "attachment_id": "attachment1", "kind": "file", "original_name": "private.txt",
            "mime_type": "text/plain", "size_bytes": asset.stat().st_size,
            "storage_path": asset.relative_to(paths.base_dir).as_posix(),
        }])
    original = reader._asset_gc.delete_message_assets
    def fail_once(references):
        monkeypatch.setattr(reader._asset_gc, "delete_message_assets", original)
        raise ChatAssetDeletionError("Injected filesystem failure")
    monkeypatch.setattr(reader._asset_gc, "delete_message_assets", fail_once)
    with pytest.raises(ChatSurfaceCleanupPendingError):
        await reader.aclear_conversation_history("u1", "s1")
    assert asset.exists()
    assert (await reader.aget_history_page("u1", "s1", limit=10))["count"] == 0
    async with store.database.session() as connection:
        row, = await connection.execute_fetchall("SELECT content_text,payload_json,is_visible FROM chat_messages")
        assert [row[index] for index in range(3)] == ["", "{}", 0]
        refs = await connection.execute_fetchall("SELECT storage_rel_path FROM chat_message_asset_refs")
        assert asset.relative_to(paths.base_dir).as_posix() in {row[0] for row in refs}
    reader.close()
    await reader.aclear_conversation_history_snapshot("u1", "s1", [accepted.message.message_id], ["t1"])
    assert not asset.exists()
    async with store.database.session() as connection:
        assert not await connection.execute_fetchall("SELECT * FROM chat_message_asset_refs")
        assert not await connection.execute_fetchall("SELECT * FROM chat_messages")
    assert not paths.chat_db_path.exists()


async def test_native_read_snapshot_and_temporary_scopes_release_pool(mysql_chat, mysql_chat_reader):
    from magi.chat.storage.relational_read.deletion_phases import replace_deletion_scope
    store, _, _ = mysql_chat
    reader = mysql_chat_reader
    await create_turn(store)
    connection = reader.database.open()
    try:
        connection.begin_read()
        assert connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1
        await create_turn(store, turn="t2")
        assert connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1
        connection.rollback()
        assert connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 2
        replace_deletion_scope(connection, message_ids=["private-id"], turn_ids=["t1"])
        connection.commit()
    finally:
        connection.close()
    connection = reader.database.open()
    try:
        replace_deletion_scope(connection, message_ids=[], turn_ids=[])
        assert connection.execute("SELECT COUNT(*) FROM chat_deletion_message_ids").fetchone()[0] == 0
        connection.rollback()
    finally:
        connection.close()


@pytest.mark.parametrize("operation", ["list_sessions", "get_display_history", "get_display_message"])
async def test_native_reader_unavailable_is_not_an_empty_result(mysql_chat_reader, monkeypatch, operation):
    from magi.core.persistence_errors import PersistenceUnavailableError
    reader = mysql_chat_reader
    def unavailable():
        raise PersistenceUnavailableError("Injected storage failure")
    monkeypatch.setattr(reader.database, "open", unavailable)
    arguments = {"list_sessions": ("u1",), "get_display_history": ("u1", "s1"),
        "get_display_message": ("u1", "s1", "m1")}
    with pytest.raises(PersistenceUnavailableError):
        getattr(reader, operation)(*arguments[operation])


async def test_native_ownership_dependencies_and_artifact_registry(mysql_chat, mysql_chat_reader, tmp_path):
    import subprocess
    from magi.chat.code_delegation_artifacts import ChatCodeDelegationArtifactRegistry
    store, database, paths = mysql_chat
    await create_turn(store)
    await store.record_consumed(session_id="s1", run_id="r1", revision=2, message_ids=["m1", "m1"])
    reopened = MysqlChatRepository(database, center_id="center-test", runtime_paths=paths)
    assert await reopened.find_runs_that_consumed(session_id="s1", message_id="m1") == [("r1", 2)]
    await reopened.clear_for_run(session_id="s1", run_id="r1")
    assert not await store.find_runs_that_consumed(session_id="s1", message_id="m1")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", str(workspace)], check=True, capture_output=True)
    registry = ChatCodeDelegationArtifactRegistry(repository=store)
    await registry.register(session_id="s1", turn_id="t1", delegation_id="a"*32, workspace_path=str(workspace))
    async with store.database.session() as connection:
        saved, = await connection.execute_fetchall("SELECT delegation_id,workspace_path FROM chat_code_delegation_artifacts")
        assert saved[0] == "a"*32 and saved[1] == str(workspace)
    await mysql_chat_reader.adelete_session("u1", "s1")
    with pytest.raises(ChatTurnConflictError):
        await registry.register(session_id="s1", turn_id="t1", delegation_id="b"*32, workspace_path=str(workspace))
    with pytest.raises(ChatTurnConflictError):
        await store.record_consumed(session_id="s1", run_id="late", revision=3, message_ids=["m1"])
    assert not paths.chat_db_path.exists()


async def test_native_asset_sweep_uses_selected_owner_and_fails_closed(mysql_chat, mysql_chat_reader, monkeypatch):
    import os
    from magi.chat.asset_gc import ChatAssetGC
    from magi.core.persistence_errors import PersistenceUnavailableError
    store, _, paths = mysql_chat
    accepted = await create_turn(store)
    directory = paths.chat_files_dir / "s1" / "t1"
    directory.mkdir(parents=True)
    owned, orphan = directory / "owned.txt", directory / "orphan.txt"
    for path in (owned, orphan):
        path.write_text("private data", encoding="utf-8")
        os.utime(path, (100_000, 100_000))
    async with store.database.session() as connection:
        await connection.execute("INSERT INTO chat_message_asset_refs(message_id,asset_key,storage_rel_path,asset_kind,created_at_ms) VALUES (?,?,?,?,?)",
            (accepted.message.message_id, owned.relative_to(paths.chat_resources_dir).as_posix(),
             owned.relative_to(paths.base_dir).as_posix(), "attachment", 100))
        await connection.commit()
    collector = ChatAssetGC(runtime_paths=paths, ownership=mysql_chat_reader, now=lambda: 400_000)
    result = collector.sweep_orphan_assets()
    assert owned.exists() and not orphan.exists()
    assert result["chat_asset_orphan_files_deleted"] == 1
    orphan.write_text("keep while ownership is unavailable", encoding="utf-8")
    os.utime(orphan, (100_000, 100_000))
    def unavailable():
        raise PersistenceUnavailableError("Injected unavailable owner")
    monkeypatch.setattr(mysql_chat_reader, "get_active_asset_ownership", unavailable)
    assert collector.sweep_orphan_assets()["chat_asset_orphan_files_deleted"] == 0
    assert owned.exists() and orphan.exists()
    assert not paths.chat_db_path.exists()
