"""Complete logical chat state survives native cutover and failed replacement."""

import sqlite3
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from pydantic import ValidationError
from magi_plugin_sdk.endpoints import EndpointRef

from _shared.db_schema import apply_chain_schema
from magi.bootstrap.storage_selection import binding_file
from magi.chat.contracts import ChatMessageRecord
from magi.chat.model_context import ModelContextItem
from magi.chat.storage.snapshots import RelationalChatStateTransfer, COLLECTIONS, TABLES
from magi.chat.storage.sqlite_store import SqliteChatRepository
from magi.chat.storage_snapshot import ChatStorageSnapshot
from magi.core.persistence_errors import PersistenceConflictError
from magi.db.logical_transfer import snapshot_digest
from magi.db.storage_bindings import StorageBindingFile
from magi.delivery.routing import DeliveryPlan
from _shared.mysql_fixtures import create_turn, mysql_chat, mysql_chat_reader


@pytest.fixture
async def transfer_environment(mysql_chat):
    from _shared.mysql_storage_plugin.database import MysqlSettings
    remote, database, paths = mysql_chat
    apply_chain_schema("chat", paths.chat_db_path)
    local = SqliteChatRepository(db_path=str(paths.chat_db_path), runtime_paths=paths)
    await local.initialize()
    binding = binding_file(paths, "chat").read_or_create()
    binding.center_id = "center-test"
    binding_file(paths, "chat").write(binding)
    url = database._engine.url
    settings = MysqlSettings(host=url.host, port=url.port, database=url.database, user=url.username,
        password=os.environ["MAGI_MYSQL_CHAT_PASSWORD"], tls=False)
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
    await destination.import_state(original)
    assert snapshot_digest(await source.export_state()) == snapshot_digest(original)
    migrated = await destination.export_state()
    assert snapshot_digest(migrated) == snapshot_digest(original)
    assert {row.state for row in migrated.outbound_deliveries} == {"uncertain", "pending"}
    assert migrated.task_execution_budgets[0].llm_calls_used == 2
    assert await remote.load_model_context(session_id="s1") == await local.load_model_context(session_id="s1")
    await create_turn(remote, turn="new-native-turn")
    with pytest.raises(ValueError, match="explicit replacement"):
        await source.import_state(await destination.export_state())
    await source.import_state(await destination.export_state(), replace=True)
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


async def test_native_snapshot_has_no_internal_key_columns(transfer_environment):
    from _shared.mysql_storage_plugin.chat.schema import CHAT_TABLES
    assert set(TABLES) == set(CHAT_TABLES)
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
