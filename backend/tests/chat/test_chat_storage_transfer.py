"""Complete logical chat state survives native cutover and failed replacement."""

import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy import text
from pydantic import ValidationError
from magi_plugin_sdk.endpoints import EndpointRef

from _shared.db_schema import apply_chain_schema
from magi.bootstrap.chat_storage_transfer import binding_file, migrate_chat_storage, preflight_storage_selection
from magi.chat.contracts import ChatMessageRecord
from magi.chat.model_context import ModelContextItem
from magi.chat.storage.mysql.schema import CHAT_TABLES
from magi.chat.storage.snapshots import RelationalChatStateTransfer, COLLECTIONS, TABLES
from magi.chat.storage.sqlite_store import SqliteChatRepository
from magi.chat.storage_snapshot import ChatStorageSnapshot
from magi.core.persistence_errors import PersistenceConflictError
from magi.db.logical_transfer import snapshot_digest
from magi.db.mysql import MysqlDatabase, MysqlSettings
from magi.chat.storage.mysql.database import MysqlChatDatabase
from magi.db.storage_bindings import StorageBindingFile
from magi.delivery.routing import DeliveryPlan
from test_mysql_chat_repository import create_turn
from test_mysql_chat_repository import mysql_chat as mysql_chat, mysql_chat_reader as mysql_chat_reader


@pytest.fixture
async def transfer_environment(mysql_chat):
    remote, database, paths = mysql_chat
    apply_chain_schema("chat", paths.chat_db_path)
    local = SqliteChatRepository(db_path=str(paths.chat_db_path), runtime_paths=paths)
    await local.initialize()
    binding = binding_file(paths).read_or_create()
    binding.center_id = "center-test"
    binding_file(paths).write(binding)
    url = database._engine.url
    settings = MysqlSettings(host=url.host, port=url.port, database=url.database, user=url.username,
        password_env="MAGI_MYSQL_CHAT_PASSWORD", tls=False)
    return local, remote, database, paths, settings


async def seed_chat(store):
    await create_turn(store)
    item = ModelContextItem.from_prompt_message({"role": "user", "content": "打开客厅灯"}, source="test")
    await store.append_model_context(session_id="s1", items=(item,), expected_revision=0)
    await store.ensure_task_execution_budget(root_turn_id="t1", max_llm_calls=5, max_worker_launches=3)
    await store.reserve_task_execution_budget(root_turn_id="t1", resource="llm_calls", count=2,
        max_llm_calls=5, max_worker_launches=3)
    message = ChatMessageRecord("reply-t1", "s1", "t1", "u1", "assistant", "assistant_final",
        "客厅灯已打开", "{}", True, True, 201, 2, None, None)
    plan = DeliveryPlan("s1", "u1", (EndpointRef("phone", "text", "owner"), EndpointRef("home", "audio", "speaker")))
    await store.commit_unmanaged_assistant_outcome(post_turn_source="conversation", turn_id="t1", messages=[message],
        attachment_payloads_by_message_id={}, trace_id=None, execution_mode="direct_llm", ux_plan={},
        response_mode="final_only", started_at_ms=100, completed_at_ms=201, delivery_plan=plan)
    first = await store.claim_outbound_delivery(now_ms=202)
    assert await store.begin_outbound_attempt(first, retry_safe=False, now_ms=203)
    assert await store.settle_outbound_delivery(first, state="uncertain", now_ms=204)
    # Preserve a receipt whose content was already irreversibly erased.
    async with store.database.session() as connection:
        await connection.execute("INSERT INTO chat_retired_turns VALUES (?, ?)", ("a" * 64, 205))
        await connection.commit()


def test_snapshot_contract_covers_every_migrated_sqlite_column(tmp_path):
    path = tmp_path / "chat.db"
    apply_chain_schema("chat", path)
    assert set(TABLES) == set(CHAT_TABLES)
    with sqlite3.connect(path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'chat_%'")}
        assert names == set(TABLES)
        for collection, table in zip(COLLECTIONS, TABLES, strict=True):
            model = ChatStorageSnapshot.model_fields[collection].annotation.__args__[0]
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert columns == set(model.model_fields)
    with pytest.raises(ValidationError):
        ChatStorageSnapshot.model_validate({"retired_turns": [{"turn_key": "a"*64, "retired_at_ms": "7"}]})


async def test_round_trip_preserves_outboxes_context_and_budget(transfer_environment):
    local, remote, _, paths, settings = transfer_environment
    await seed_chat(local)
    source = RelationalChatStateTransfer(local.database)
    destination = RelationalChatStateTransfer(remote.database)
    original = await source.export_state()
    with pytest.raises(RuntimeError, match="Local chat data exists"):
        await preflight_storage_selection(paths, "mysql", settings)
    await migrate_chat_storage(paths, destination="mysql", mysql=settings)
    assert snapshot_digest(await source.export_state()) == snapshot_digest(original)
    migrated = await destination.export_state()
    assert snapshot_digest(migrated) == snapshot_digest(original)
    assert {row.state for row in migrated.outbound_deliveries} == {"uncertain", "pending"}
    assert migrated.task_execution_budgets[0].llm_calls_used == 2
    assert await remote.load_model_context(session_id="s1") == await local.load_model_context(session_id="s1")
    await create_turn(remote, turn="new-native-turn")
    with pytest.raises(ValueError, match="Destination has data"):
        await migrate_chat_storage(paths, destination="sqlite", mysql=settings)
    await migrate_chat_storage(paths, destination="sqlite", mysql=settings, replace_destination=True)
    assert snapshot_digest(await source.export_state()) == snapshot_digest(await destination.export_state())


@pytest.mark.parametrize("closed", ["archived_at_ms", "deleted_at_ms"])
async def test_closed_session_and_cleanup_fences_round_trip(transfer_environment, closed):
    local, remote, _, _, _ = transfer_environment
    accepted = await create_turn(local)
    async with local.database.session() as connection:
        if closed == "deleted_at_ms":
            await connection.execute("UPDATE chat_messages SET content_text='',payload_json='{}',is_visible=0")
        await connection.execute(f"UPDATE chat_sessions SET {closed}=300 WHERE session_id='s1'")
        if closed == "deleted_at_ms":
            await connection.execute("INSERT INTO chat_cleared_message_scopes VALUES ('s1', ?, 300)", (accepted.message.message_id,))
            await connection.execute("INSERT INTO chat_global_clear_intent VALUES ('global',300,1)")
        await connection.commit()
    source = RelationalChatStateTransfer(local.database)
    destination = RelationalChatStateTransfer(remote.database)
    snapshot = await source.export_state()
    await destination.import_state(snapshot)
    assert snapshot_digest(await destination.export_state()) == snapshot_digest(snapshot)
    await source.import_state(await destination.export_state(), replace=True)
    assert snapshot_digest(await source.export_state()) == snapshot_digest(snapshot)


@pytest.mark.parametrize("target_kind", ["sqlite", "mysql"])
async def test_failed_replacement_rolls_back_every_collection(transfer_environment, target_kind):
    local, remote, _, _, _ = transfer_environment
    await seed_chat(local)
    await create_turn(remote, turn="existing-target")
    target = RelationalChatStateTransfer(remote.database if target_kind == "mysql" else local.database)
    before = await target.export_state()
    invalid = await RelationalChatStateTransfer(local.database).export_state()
    invalid.outbound_deliveries[0].session_id = "missing-foreign-session"
    with pytest.raises(PersistenceConflictError):
        await target.import_state(invalid, replace=True)
    assert snapshot_digest(await target.export_state()) == snapshot_digest(before)


async def test_cutover_recovery_verifies_import_without_repeating_it(transfer_environment, monkeypatch):
    local, _, _, paths, settings = transfer_environment
    await seed_chat(local)
    write_binding = StorageBindingFile.write
    def fail_activation(self, binding):
        if binding.active and binding.active.kind == "mysql" and binding.pending is None:
            raise OSError("Injected activation failure")
        write_binding(self, binding)
    monkeypatch.setattr(StorageBindingFile, "write", fail_activation)
    with pytest.raises(OSError, match="activation failure"):
        await migrate_chat_storage(paths, destination="mysql", mysql=settings)
    assert binding_file(paths).read_or_create().pending is not None
    with pytest.raises(RuntimeError, match="incomplete"):
        await preflight_storage_selection(paths, "mysql", settings)
    monkeypatch.setattr(StorageBindingFile, "write", write_binding)
    async def no_repeat(*args, **kwargs):
        raise AssertionError("Already confirmed import must not run twice")
    monkeypatch.setattr(RelationalChatStateTransfer, "import_state", no_repeat)
    await migrate_chat_storage(paths, destination="mysql", mysql=settings)
    assert binding_file(paths).read_or_create().pending is None


async def test_native_snapshot_has_no_internal_key_columns(transfer_environment):
    local, remote, database, _, _ = transfer_environment
    await seed_chat(local)
    snapshot = await RelationalChatStateTransfer(local.database).export_state()
    await RelationalChatStateTransfer(remote.database).import_state(snapshot)
    async with database.transaction() as connection:
        for collection, table in zip(COLLECTIONS, TABLES, strict=True):
            columns = (await connection.execute(text(f"SHOW COLUMNS FROM {table}"))).all()
            fields = {row[0] for row in columns if not row[0].startswith("__")}
            model = ChatStorageSnapshot.model_fields[collection].annotation.__args__[0]
            assert fields == set(model.model_fields)


async def test_remote_to_remote_requires_exact_source_and_preserves_local_store(transfer_environment):
    local, remote, database, paths, settings = transfer_environment
    await seed_chat(local)
    await migrate_chat_storage(paths, destination="mysql", mysql=settings)
    await create_turn(remote, turn="remote-only")
    local_before = snapshot_digest(await RelationalChatStateTransfer(local.database).export_state())
    remote_before = snapshot_digest(await RelationalChatStateTransfer(remote.database).export_state())
    name = "magi_test_chat_destination_" + uuid4().hex
    async with database.transaction() as connection:
        await connection.execute(text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"))
    target_settings = settings.model_copy(update={"database": name})
    destination = MysqlDatabase(target_settings)
    try:
        with pytest.raises(ValueError, match="Source MySQL settings"):
            await migrate_chat_storage(paths, destination="mysql", mysql=target_settings)
        await migrate_chat_storage(paths, destination="mysql", mysql=target_settings, source_mysql=settings)
        adapter = MysqlChatDatabase(destination, center_id="center-test")
        await adapter.initialize()
        assert snapshot_digest(await RelationalChatStateTransfer(adapter).export_state()) == remote_before
        assert snapshot_digest(await RelationalChatStateTransfer(remote.database).export_state()) == remote_before
        assert snapshot_digest(await RelationalChatStateTransfer(local.database).export_state()) == local_before
    finally:
        await destination.close()
        async with database.transaction() as connection:
            await connection.execute(text(f"DROP DATABASE {name}"))
