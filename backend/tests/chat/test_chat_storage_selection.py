"""Startup selects one chat owner and never silently falls back to local data."""

from types import SimpleNamespace

import pytest

from magi.bootstrap.chat_storage import compose_chat_storage
from magi.bootstrap.chat_storage_transfer import binding_file, storage_target
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.runtime_worker_builder import _build_infrastructure_modules
from magi.bootstrap.structured_storage import StructuredStorageModule
from magi.chat.provider import get_chat_read_service, get_chat_store
from magi.chat.storage.snapshots import RelationalChatStateTransfer
from magi.config.storage_models import StructuredStorageSettings
from magi.core.container import init_container
from magi.core.persistence_errors import PersistenceConflictError
from magi.db.logical_transfer import snapshot_digest
from magi.db.mysql import MysqlDatabase, MysqlSettings
from magi.utils.runtime import RuntimePaths
from test_chat_storage_transfer import transfer_environment as transfer_environment
from test_mysql_chat_repository import mysql_chat as mysql_chat, create_turn


async def test_sqlite_selection_publishes_before_chat_consumers(tmp_path, ensure_db_schema):
    paths = RuntimePaths(base_dir=tmp_path)
    for name, path in (("chat", paths.chat_db_path), ("l1", paths.l1_memory_db_path),
                       ("channels", paths.channels_db_path)):
        ensure_db_schema(name, path)
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.config = SimpleNamespace(structured_storage=StructuredStorageSettings())
    module = StructuredStorageModule(context)
    init_container()
    modules = {item.name: item for item in _build_infrastructure_modules(context)}
    exports = modules["runtime_chat_storage_exports"]
    assert exports.dependencies == ("runtime_structured_storage",)
    assert exports.name in modules["runtime_chat_store"].dependencies
    await module.init()
    try:
        await exports.init()
        assert get_chat_store() is context.chat.store
        assert get_chat_read_service() is context.chat.reader
        await create_turn(get_chat_store())
        assert (await context.chat.state_transfer.export_state()).messages[0].content_text
    finally:
        await exports.shutdown()
        await module.shutdown()
    with pytest.raises(RuntimeError, match="chat_read_service"):
        get_chat_read_service()
    assert context.chat.store is context.chat.reader is context.chat.state_transfer is None


async def test_selected_mysql_reader_and_writer_reopen_without_touching_local_data(transfer_environment):
    local, _, _, paths, mysql = transfer_environment
    before = snapshot_digest(await RelationalChatStateTransfer(local.database).export_state())
    config = StructuredStorageSettings(chat="mysql", mysql=mysql)
    for index in range(2):
        database = MysqlDatabase(mysql)
        runtime = await compose_chat_storage(paths, config, database)
        try:
            assert runtime.read_pool is not None
            if index == 0:
                await create_turn(runtime.store)
            snapshot = await runtime.state_transfer.export_state()
            assert len(snapshot.turns) == 1
            assert await runtime.reader.aget_interrupted_global_clear_count() is None
            assert await runtime.reader.aget_session_summary("u1", "s1") is not None
        finally:
            await runtime.close()
            assert runtime.read_pool._engine.pool.checkedout() == 0
            await database.close()
    assert binding_file(paths).read_or_create().active == storage_target("mysql", mysql)
    assert snapshot_digest(await RelationalChatStateTransfer(local.database).export_state()) == before


async def test_changed_chat_binding_rejected_before_connecting(tmp_path, ensure_db_schema, monkeypatch):
    paths = RuntimePaths(base_dir=tmp_path)
    for name, path in (("chat", paths.chat_db_path), ("l1", paths.l1_memory_db_path),
                       ("channels", paths.channels_db_path)):
        ensure_db_schema(name, path)
    runtime = await compose_chat_storage(paths, StructuredStorageSettings(), None)
    await runtime.close()
    mysql = MysqlSettings(host="127.0.0.1", database="unreachable", user="root",
        password_env="ABSENT_MYSQL_PASSWORD", tls=False)
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.config = SimpleNamespace(
        structured_storage=StructuredStorageSettings(chat="mysql", mysql=mysql))
    def unexpected_connect(*args):
        pytest.fail("Storage fencing must precede connection construction")
    monkeypatch.setattr("magi.bootstrap.structured_storage.MysqlDatabase", unexpected_connect)
    with pytest.raises(RuntimeError, match="Chat storage changed"):
        await StructuredStorageModule(context).init()


async def test_foreign_chat_center_cannot_publish_binding(transfer_environment, tmp_path):
    _, _, database, _, mysql = transfer_environment
    paths = RuntimePaths(base_dir=tmp_path / "foreign-center")
    with pytest.raises(PersistenceConflictError, match="another center"):
        await compose_chat_storage(paths, StructuredStorageSettings(chat="mysql", mysql=mysql), database)
    assert binding_file(paths).read_or_create().active is None


def test_mysql_chat_requires_connection_settings():
    with pytest.raises(ValueError, match="MySQL connection settings"):
        StructuredStorageSettings(chat="mysql")


def test_offline_cli_requires_matching_config_and_exclusive_lease(tmp_path, monkeypatch, capsys):
    from magi.bootstrap.chat_storage_transfer import main
    from magi.utils.worker_instance import WorkerInstance
    from magi_plugin_sdk.fs import atomic_write_managed_bytes

    config = tmp_path / "config" / "agent.yaml"
    config.parent.mkdir(mode=0o700)
    atomic_write_managed_bytes(config, b"structured_storage: {chat: sqlite}\n")
    monkeypatch.setattr("sys.argv", ["chat_storage_transfer", "--root", str(tmp_path), "--target", "mysql"])
    with pytest.raises(ValueError, match="Configure the requested chat storage target"):
        main()
    monkeypatch.setattr("sys.argv", ["chat_storage_transfer", "--root", str(tmp_path), "--target", "sqlite"])
    with WorkerInstance(tmp_path):
        with pytest.raises(RuntimeError, match="already owns"):
            main()
    main()
    assert '"status": "unchanged"' in capsys.readouterr().out
