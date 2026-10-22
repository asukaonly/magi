"""Real cross-database migration, restart fencing and source preservation."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from magi.bootstrap.channel_storage import (
    binding_file, configured_target, migrate_channel_storage, verify_storage_selection,
)
from magi.channels.persistence.snapshots import SqliteChannelStateTransfer, MysqlChannelStateTransfer
from magi.channels.storage_snapshot import ChannelStorageSnapshot
from magi.config.storage_models import StructuredStorageSettings
from magi.db.logical_transfer import snapshot_digest
from magi.db.mysql import MysqlDatabase, MysqlSettings
from magi.db.mysql_migrations import upgrade_mysql_channels
from magi.db.storage_bindings import StorageBindingFile
from magi.utils.runtime import RuntimePaths


@pytest.fixture
async def environment(tmp_path, monkeypatch, ensure_db_schema):
    port = os.environ.get("MAGI_TEST_MYSQL_PORT")
    if not port:
        pytest.skip("Set MAGI_TEST_MYSQL_PORT to run real storage migration tests")
    monkeypatch.setenv("MAGI_MYSQL_TRANSFER_PASSWORD",os.environ.get("MAGI_TEST_MYSQL_PASSWORD",""))
    settings = MysqlSettings(host="127.0.0.1",port=int(port),database="magi_test_architecture",
                            user=os.environ.get("MAGI_TEST_MYSQL_USER","root"),password_env="MAGI_MYSQL_TRANSFER_PASSWORD",tls=False)
    admin = MysqlDatabase(settings)
    name = "magi_test_transfer_" + uuid4().hex
    async with admin.transaction() as db:
        await db.execute(text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"))
    mysql = settings.model_copy(update={"database":name})
    paths = RuntimePaths(base_dir=tmp_path)
    ensure_db_schema("channels",paths.channels_db_path)
    ensure_db_schema("l1",paths.l1_memory_db_path)
    ensure_db_schema("chat",paths.chat_db_path)
    config = StructuredStorageSettings(channels="mysql",mysql=mysql)
    try:
        yield paths,config
    finally:
        async with admin.transaction() as db:
            await db.execute(text(f"DROP DATABASE {name}"))
        await admin.close()


def sample_snapshot():
    return ChannelStorageSnapshot.model_validate({
        "bindings":[dict(channel_type="channel.a.telegram",external_chat_id="chat",external_thread_id="thread",
                         magi_session_id="session",magi_user_id="local_user",is_group=True,created_at_ms=1,last_active_at_ms=2,metadata_json='{"name":"中文"}')],
        "notification_cursors":[dict(channel_type="channel.a.telegram",external_chat_id="chat",last_notification_id=100,updated_at_ms=1)],
        "relay_cursors":[dict(state_key="relay",value_integer=42,updated_at_ms=1)],
        "binding_settings":[dict(channel_type="channel.a.telegram",external_user_id="person",auto_approve=True,updated_at_ms=1)],
        "delivery_receipts":[dict(receipt_id=91,session_id="session",run_id="run",revision=2,channel_id="channel.a.telegram",external_message_id="native-message",magi_session_id="session",delivered_at_ms=3,created_at_ms=3)],
        "outreach_intents":[dict(id=index+10,correlation_id="event-"+status,channel_scope="channel.a.telegram",intent_fingerprint="fingerprint",intent_json='{}',release_at_ms=3,status=status,created_at_ms=1) for index,status in enumerate(("pending","attempting","uncertain","delivered"))],
        "outreach_receipts":[dict(correlation_id="delivered-event",user_id="local_user",channel_type="channel.a.telegram",delivered_at_ms=3)],
    })


async def test_sqlite_mysql_sqlite_transfer_preserves_complete_logical_state(environment):
    paths,config = environment
    local = SqliteChannelStateTransfer(str(paths.channels_db_path))
    snapshot = sample_snapshot()
    await local.import_state(snapshot)
    with pytest.raises(RuntimeError,match="Local channel data exists"):
        await verify_storage_selection(paths,config,None)
    result = await migrate_channel_storage(paths,config)
    assert result["status"] == "migrated"
    assert snapshot_digest(await local.export_state()) == snapshot_digest(snapshot)
    database = MysqlDatabase(config.mysql)
    try:
        await verify_storage_selection(paths,config,database)
        remote = MysqlChannelStateTransfer(database)
        recovered = await remote.export_state()
        assert snapshot_digest(recovered) == snapshot_digest(snapshot)
        # A new remote fact must survive a round trip; old SQLite content is retained until explicit replacement.
        recovered.relay_cursors[0].value_integer = 99
        await remote.import_state(recovered,replace=True)
        back = config.model_copy(update={"channels":"sqlite"})
        with pytest.raises(ValueError,match="Destination has data"):
            await migrate_channel_storage(paths,back)
        assert binding_file(paths).read_or_create().pending is None
        await migrate_channel_storage(paths,back,replace_destination=True)
        assert snapshot_digest(await local.export_state()) == snapshot_digest(recovered)
        assert (await remote.export_state()).relay_cursors[0].value_integer == 99
        await verify_storage_selection(paths,back,None)
    finally:
        await database.close()


async def test_interrupted_cutover_blocks_boot_and_resumes_without_duplicate_import(environment,monkeypatch):
    paths,config = environment
    local = SqliteChannelStateTransfer(str(paths.channels_db_path))
    snapshot = sample_snapshot()
    await local.import_state(snapshot)
    original = StorageBindingFile.write
    failed = False
    def fail_final_binding(self,binding):
        nonlocal failed
        if binding.active is not None and binding.active.kind == "mysql" and binding.pending is None and not failed:
            failed = True
            raise OSError("simulated cutover crash")
        original(self,binding)
    monkeypatch.setattr(StorageBindingFile,"write",fail_final_binding)
    with pytest.raises(OSError,match="cutover crash"):
        await migrate_channel_storage(paths,config)
    assert binding_file(paths).read_or_create().pending is not None
    with pytest.raises(RuntimeError,match="incomplete"):
        await verify_storage_selection(paths,config,None)
    await migrate_channel_storage(paths,config)
    binding = binding_file(paths).read_or_create()
    assert binding.pending is None
    assert binding.active == configured_target(paths,config)
    assert snapshot_digest(await local.export_state()) == snapshot_digest(snapshot)


async def test_a_different_center_cannot_attach_existing_mysql_state(environment,tmp_path):
    paths,config = environment
    await migrate_channel_storage(paths,config)
    second = RuntimePaths(base_dir=tmp_path / "second-center")
    from magi.db.runner import run_upgrade_database
    run_upgrade_database("channels",second.channels_db_path)
    database = MysqlDatabase(config.mysql)
    try:
        with pytest.raises(RuntimeError,match="another logical center"):
            await verify_storage_selection(second,config,database)
    finally:
        await database.close()


async def test_failed_mysql_replacement_rolls_back_deletions(environment):
    _,config = environment
    database = MysqlDatabase(config.mysql)
    try:
        await upgrade_mysql_channels(database)
        store = MysqlChannelStateTransfer(database)
        first = sample_snapshot()
        await store.import_state(first)
        replacement = sample_snapshot()
        replacement.relay_cursors[0].value_integer = 99
        # Fail on a later collection, after earlier destination rows were replaced.
        async with database.transaction() as db:
            await db.execute(text("""CREATE TRIGGER reject_transfer BEFORE INSERT ON outreach_outbox
                FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='injected migration failure'"""))
        with pytest.raises(RuntimeError,match="could not be confirmed"):
            await store.import_state(replacement,replace=True)
        assert snapshot_digest(await store.export_state()) == snapshot_digest(first)
    finally:
        await database.close()


async def test_bootstrap_reopens_selected_mysql_repositories(environment):
    paths,config = environment
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.bootstrap.structured_storage import StructuredStorageModule
    from magi.config.models import AppConfig
    from magi.channels.contracts import ChannelSessionMapping
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.config = AppConfig(structured_storage=config)
    module = StructuredStorageModule(context)
    await module.init()
    try:
        await context.channels.repositories.sessions.insert(ChannelSessionMapping(
            channel_type="channel.a.telegram",external_chat_id="chat",external_thread_id="thread",
            magi_session_id="session",magi_user_id="local_user",is_group=False,
            created_at_ms=1,last_active_at_ms=1,metadata_json="{}",
        ))
    finally:
        await module.shutdown()
    restarted = StructuredStorageModule(context)
    await restarted.init()
    try:
        recovered = await context.channels.repositories.sessions.lookup("channel.a.telegram","chat",external_thread_id="thread")
        assert recovered.magi_session_id == "session"
    finally:
        await restarted.shutdown()
    assert context.channels.repositories is None
    assert context.outreach.repositories is None


async def test_config_switch_is_rejected_before_connecting_to_destination(tmp_path,ensure_db_schema,monkeypatch):
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.bootstrap.structured_storage import StructuredStorageModule
    from magi.config.models import AppConfig
    paths = RuntimePaths(base_dir=tmp_path)
    ensure_db_schema("channels",paths.channels_db_path)
    await verify_storage_selection(paths,StructuredStorageSettings(),None)
    config = StructuredStorageSettings(channels="mysql",mysql=MysqlSettings(
        host="127.0.0.1",database="magi_test_unreachable",user="root",password_env="MISSING_MYSQL_PASSWORD",tls=False,
    ))
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.config = AppConfig(structured_storage=config)
    with pytest.raises(RuntimeError,match="storage changed"):
        await StructuredStorageModule(context).init()
