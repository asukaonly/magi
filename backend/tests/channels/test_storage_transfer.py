"""Real plugin cutover preserves all domains and fences interrupted activation."""

import pytest
from _shared.storage_plugins import (
    mysql_package, mysql_settings, storage_environment, select, start, stop, install_mysql,
)
from magi.bootstrap.storage_selection import binding_file
from magi.bootstrap.storage_transfer import migrate_storage
from magi.config.storage_models import StructuredStorageSettings
from magi.db.logical_transfer import snapshot_digest
from magi.db.storage_bindings import StorageBindingFile
from magi.channels.contracts import ChannelSessionMapping
from memory.l1.test_event_repository import command

DOMAINS = ("channels", "memory_events", "chat")


def transfer(context, domain):
    if domain == "chat":
        return context.chat.state_transfer
    if domain == "memory_events":
        return context.memory.event_state_transfer
    return context._storage_module.sessions[0].transfer


async def seed(context, domain, key):
    if domain == "chat":
        await context.chat.store.create_user_turn_once(session_id="s", user_id="u", turn_id=key,
            message_text=key, created_at_ms=100, request_fingerprint=key,
            runtime_envelope={"session_id": "s", "turn_id": key, "message": key, "attachments": [], "metadata": {}})
        assert await context.chat.reader.aget_session_summary("u", "s") is not None
    elif domain == "memory_events":
        await context.memory.event_repository.append(command(key))
    else:
        await context.channels.repositories.sessions.insert(ChannelSessionMapping(
            channel_type="channel.test", external_chat_id=key, external_thread_id=None,
            magi_session_id=key, magi_user_id="u", is_group=False,
            created_at_ms=1, last_active_at_ms=1, metadata_json="{}"))


async def boot(paths, config):
    context, module = await start(paths, config)
    context._storage_module = module
    return context, module


@pytest.mark.parametrize("domain", DOMAINS)
async def test_sqlite_mysql_sqlite_complete_cutover(storage_environment, domain):
    paths, remote = storage_environment
    local = StructuredStorageSettings()
    context, module = await boot(paths, local)
    try:
        await seed(context, domain, "original")
        before = await transfer(context, domain).export_state()
    finally:
        await stop(context, module)
    external = local.model_copy(update={domain: remote})
    select(paths, external)
    with pytest.raises(RuntimeError, match="selection changed"):
        await start(paths, external)
    await migrate_storage(paths, domain)
    context, module = await boot(paths, external)
    try:
        assert snapshot_digest(await transfer(context, domain).export_state()) == snapshot_digest(before)
        await seed(context, domain, "remote-added")
        final = await transfer(context, domain).export_state()
        with pytest.raises(ValueError, match="storage|Storage"):
            context.plugins.storage_runtime.require_mutable("storage-mysql", remote.connection_id)
    finally:
        await stop(context, module)
    select(paths, local)
    with pytest.raises(ValueError, match="Destination has data"):
        await migrate_storage(paths, domain)
    await migrate_storage(paths, domain, replace_destination=True)
    context, module = await boot(paths, local)
    try:
        assert snapshot_digest(await transfer(context, domain).export_state()) == snapshot_digest(final)
    finally:
        await stop(context, module)


@pytest.mark.parametrize("domain", DOMAINS)
async def test_interrupted_activation_retains_intent_and_resumes(storage_environment, domain, monkeypatch):
    paths, remote = storage_environment
    context, module = await boot(paths, StructuredStorageSettings())
    try:
        await seed(context, domain, "retained")
        before = snapshot_digest(await transfer(context, domain).export_state())
    finally:
        await stop(context, module)
    external = StructuredStorageSettings().model_copy(update={domain: remote})
    select(paths, external)
    write = StorageBindingFile.write
    def interrupt(self, binding):
        if binding.active is not None and binding.active.plugin_id == "storage-mysql" and binding.pending is None:
            raise OSError("activation interrupted")
        write(self, binding)
    monkeypatch.setattr(StorageBindingFile, "write", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        await migrate_storage(paths, domain)
    assert binding_file(paths, domain).read_or_create().pending is not None
    with pytest.raises(RuntimeError, match="incomplete"):
        await start(paths, external)
    monkeypatch.setattr(StorageBindingFile, "write", write)
    from magi.db.storage_transfer_proxy import StorageTransferProxy
    async def no_repeat(*args, **kwargs):
        pytest.fail("A verified import must not be repeated")
    monkeypatch.setattr(StorageTransferProxy, "import_state", no_repeat)
    await migrate_storage(paths, domain)
    context, module = await boot(paths, external)
    try:
        assert snapshot_digest(await transfer(context, domain).export_state()) == before
    finally:
        await stop(context, module)


@pytest.mark.parametrize("domain", DOMAINS)
async def test_remote_to_remote_uses_recorded_connection_and_preserves_source(storage_environment, mysql_settings, mysql_package, domain):
    from _shared.mysql_storage_plugin.database import MysqlDatabase
    from sqlalchemy import text
    from uuid import uuid4
    paths, remote = storage_environment
    first_config = StructuredStorageSettings().model_copy(update={domain: remote})
    select(paths, first_config)
    context, module = await boot(paths, first_config)
    try:
        await seed(context, domain, "remote-source")
        original = snapshot_digest(await transfer(context, domain).export_state())
    finally:
        await stop(context, module)
    admin = MysqlDatabase(mysql_settings)
    name = "magi_test_destination_" + uuid4().hex
    async with admin.transaction() as db:
        await db.execute(text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"))
    try:
        second = await install_mysql(paths, mysql_package, mysql_settings.model_copy(update={"database": name}))
        destination_config = first_config.model_copy(update={domain: second})
        select(paths, destination_config)
        await migrate_storage(paths, domain)
        context, module = await boot(paths, destination_config)
        try:
            assert snapshot_digest(await transfer(context, domain).export_state()) == original
        finally:
            await stop(context, module)
        # The recorded source connection remains independently readable after cutover.
        from magi.bootstrap.storage_plugins import build_storage_plugin_runtime
        from magi.bootstrap.storage_selection import resolve_storage, open_storage
        runtime = build_storage_plugin_runtime(paths)
        source = None
        try:
            entry, target = await resolve_storage(runtime, remote, domain)
            source = await open_storage(entry, target, domain, binding_file(paths, domain).read_or_create().center_id,
                migrate=False, maintenance=True)
            assert snapshot_digest(await source.transfer.export_state()) == original
        finally:
            if source is not None:
                await source.close()
            await runtime.close()
    finally:
        async with admin.transaction() as db:
            await db.execute(text(f"DROP DATABASE {name}"))
        await admin.close()


async def test_foreign_center_cannot_bind_an_existing_mysql_owner(storage_environment, mysql_settings, mysql_package, tmp_path):
    from magi.utils.runtime import RuntimePaths
    paths, remote = storage_environment
    config = StructuredStorageSettings(chat=remote)
    select(paths, config)
    context, module = await boot(paths, config)
    try:
        await seed(context, "chat", "retained")
    finally:
        await stop(context, module)
    foreign = RuntimePaths(base_dir=tmp_path / "foreign")
    selected = await install_mysql(foreign, mysql_package, mysql_settings)
    foreign_config = StructuredStorageSettings(chat=selected)
    select(foreign, foreign_config)
    with pytest.raises(RuntimeError, match="another center"):
        await start(foreign, foreign_config)
    assert binding_file(foreign, "chat").read_or_create().active is None


async def test_worker_loss_never_falls_back_to_sqlite(storage_environment):
    from magi.core.persistence_errors import PersistenceUnavailableError
    from magi.plugins.process_runtime import PluginProcessError
    paths, remote = storage_environment
    config = StructuredStorageSettings(chat=remote)
    select(paths, config)
    context, module = await boot(paths, config)
    try:
        await seed(context, "chat", "retained")
        context.plugins.storage_runtime.instances[remote.connection_id]._terminate()
        with pytest.raises(PersistenceUnavailableError, match="not be confirmed"):
            await context.chat.reader.aget_session_summary("u", "s")
        assert not paths.chat_db_path.exists()
        assert binding_file(paths, "chat").read_or_create().active.connection_id == remote.connection_id
    finally:
        try:
            await stop(context, module)
        except (PluginProcessError, PersistenceUnavailableError):
            pass


async def test_chat_outcome_delivery_and_cleanup_cross_worker_contract(storage_environment, ensure_db_schema):
    from magi.chat.contracts import ChatMessageRecord
    from magi.delivery.routing import DeliveryPlan
    from magi_plugin_sdk.endpoints import EndpointRef
    paths, remote = storage_environment
    ensure_db_schema("runtime_trace", paths.runtime_trace_db_path)
    config = StructuredStorageSettings(chat=remote)
    select(paths, config)
    context, module = await boot(paths, config)
    try:
        await seed(context, "chat", "turn")
        reply = ChatMessageRecord("reply", "s", "turn", "u", "assistant", "assistant_final",
            "Done", "{}", True, True, 201, 2, None, None)
        assert await context.chat.store.commit_unmanaged_assistant_outcome(
            post_turn_source="conversation", turn_id="turn", messages=[reply], attachment_payloads_by_message_id={},
            trace_id=None, execution_mode="direct_llm", ux_plan={}, response_mode="final_only",
            started_at_ms=100, completed_at_ms=201,
            delivery_plan=DeliveryPlan("s", "u", (EndpointRef("phone", "message", "owner"),)))
        delivery = await context.chat.store.claim_outbound_delivery(now_ms=202)
        assert await context.chat.store.begin_outbound_attempt(delivery, retry_safe=False, now_ms=203)
        assert await context.chat.store.settle_outbound_delivery(delivery, state="uncertain", now_ms=204)
        snapshot = await context.chat.state_transfer.export_state()
        assert snapshot.outbound_deliveries[0].state == "uncertain" and snapshot.post_turn_outcomes
        await context.chat.reader.aclear_conversation_history("u", "s")
        assert await context.chat.store.list_recent_outbound_status() == []
        snapshot = await context.chat.state_transfer.export_state()
        assert all(not item.content_text for item in snapshot.messages)
        assert all(not item.content.text for item in await context.chat.store.list_outbound_deliveries(message_id="reply"))
    finally:
        await stop(context, module)
