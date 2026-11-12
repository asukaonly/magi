"""Default storage publication and selection fencing precede domain consumers."""

from types import SimpleNamespace
import pytest
from _shared.storage_plugins import start, stop
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.storage_plugins import build_storage_plugin_runtime
from magi.bootstrap.storage_selection import binding_file
from magi.bootstrap.structured_storage import StructuredStorageModule
from magi.config.storage_models import StructuredStorageSettings, StorageSelection
from magi.utils.runtime import RuntimePaths


async def test_sqlite_selection_publishes_all_domains_and_reopens(tmp_path):
    paths = RuntimePaths(base_dir=tmp_path)
    for index in range(2):
        context, module = await start(paths, StructuredStorageSettings())
        try:
            if index == 0:
                await context.chat.store.create_user_turn_once(session_id="s", user_id="u", turn_id="t",
                    message_text="hello", created_at_ms=100, request_fingerprint="hello",
                    runtime_envelope={"session_id": "s", "turn_id": "t", "message": "hello", "attachments": [], "metadata": {}})
            assert (await context.chat.state_transfer.export_state()).messages[0].content_text == "hello"
            for domain in ("chat", "channels", "memory_events"):
                assert binding_file(paths, domain).read_or_create().active.plugin_id == "storage-sqlite"
            connection_id = binding_file(paths, "chat").read_or_create().active.connection_id
            with pytest.raises(ValueError, match="storage|Storage"):
                context.plugins.storage_runtime.require_mutable("storage-sqlite", connection_id)
        finally:
            await stop(context, module)
        assert context.chat.store is context.chat.reader is context.chat.state_transfer is None


async def test_changed_binding_is_rejected_before_any_provider_open(tmp_path, monkeypatch):
    paths = RuntimePaths(base_dir=tmp_path)
    context, module = await start(paths, StructuredStorageSettings())
    await stop(context, module)
    binding = binding_file(paths, "chat").read_or_create()
    binding.active = binding.active.model_copy(update={"identity": "different-database"})
    binding_file(paths, "chat").write(binding)
    context.plugins.storage_runtime = build_storage_plugin_runtime(paths)
    from magi.bootstrap.sqlite_storage_provider import SqliteStorageProvider
    async def unexpected(*args):
        pytest.fail("All binding checks must precede any provider open")
    monkeypatch.setattr(SqliteStorageProvider, "open", unexpected)
    try:
        with pytest.raises(RuntimeError, match="selection changed"):
            await StructuredStorageModule(context).init()
    finally:
        await context.plugins.storage_runtime.close()


def test_storage_config_rejects_legacy_kind_and_missing_connection():
    with pytest.raises(ValueError):
        StructuredStorageSettings(chat="mysql")
    with pytest.raises(ValueError):
        StorageSelection(provider_id="mysql")


def test_offline_cli_requires_exclusive_lease(tmp_path, monkeypatch):
    from magi.bootstrap.chat_storage_transfer import main
    from magi.utils.worker_instance import WorkerInstance
    monkeypatch.setattr("sys.argv", ["chat_storage_transfer", "--root", str(tmp_path)])
    with WorkerInstance(tmp_path):
        with pytest.raises(RuntimeError, match="already owns"):
            main()


async def test_normal_plugin_manager_adopts_storage_without_replacing_or_stopping_it(tmp_path):
    from magi.plugins.manager import PluginManager
    from magi.plugins.connections import PluginConnectionStore
    from magi.plugins.discovery import default_builtin_root
    paths = RuntimePaths(base_dir=tmp_path)
    context, module = await start(paths, StructuredStorageSettings())
    runtime = context.plugins.storage_runtime
    manager = PluginManager(search_paths=[default_builtin_root()], storage_runtime=runtime,
                            connection_store=PluginConnectionStore(runtime_paths=paths, require_package=lambda _: None),
                            tool_registry=None, source_registry=None,
                            request_source_schedule_refresh=lambda: None)
    try:
        manager.scan(persist_discovery=False)
        manager.adopt_storage_instances()
        connection = runtime.connections.list("storage-sqlite")[0]
        instance = runtime.instances[connection.connection_id]
        assert manager.load_connection(connection.connection_id) is instance
        for action in (
            lambda: manager.update_connection(connection.connection_id, expected_revision=connection.revision, enabled=False),
            lambda: manager.unload_connection(connection.connection_id),
            lambda: manager.disconnect_connection(connection.connection_id, expected_revision=connection.revision),
            lambda: manager.uninstall_plugin("storage-sqlite"),
        ):
            with pytest.raises(ValueError, match="storage|Storage"):
                action()
        await manager.shutdown()
        assert len(instance._provider.sessions) == 3
        assert (await context.chat.state_transfer.export_state()).is_empty()
    finally:
        await stop(context, module)


def test_offline_cli_resolves_installed_plugins_under_its_explicit_root(tmp_path, monkeypatch):
    import os
    from magi.bootstrap.storage_transfer import main
    monkeypatch.setenv("MAGI_HOME", str(tmp_path / "other"))
    monkeypatch.setattr("sys.argv", ["storage_transfer", "--root", str(tmp_path), "--domain", "chat"])
    async def check(paths, domain, *, replace_destination):
        from magi.plugins.package_files import user_plugins_root
        assert os.environ["MAGI_HOME"] == str(tmp_path)
        assert user_plugins_root() == tmp_path / "plugins"
        assert paths.base_dir == tmp_path and domain == "chat"
        return {"status": "verified"}
    monkeypatch.setattr("magi.bootstrap.storage_transfer.migrate_storage", check)
    main()
