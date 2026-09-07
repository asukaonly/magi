"""Worker failures revoke only the failed connection's runtime ownership."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.manager import PluginManager
from magi.plugins.process_runtime import ProcessPluginProxy
from magi.plugins.sources import SourceRegistry
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths
from magi_plugin_sdk import Plugin, PluginManifest, PluginPackageState
from magi_plugin_sdk.contracts import PluginSettingsActionSpec
from magi_plugin_sdk.runtime import ConnectionStatus
from magi_plugin_sdk.sources import SourceSpec
from magi_plugin_sdk.tools import Tool, ToolResult, ToolSchema


class SampleTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(
            name="sample", description="Read sample", category="test",
            effect_class="read_only", effect_replay_policy="read_only",
        )

    async def execute(self, parameters, context):
        return ToolResult(success=True, data={"ok": True})


class ControlledWorker(ProcessPluginProxy):
    """Control death and delivery separately without launching a child process."""

    def __init__(self, manifest, connection, context):
        Plugin.__init__(self)
        self.configure(manifest=manifest, connection=connection, context=context)
        self._lock = threading.RLock()
        self._catalog = {
            name: [] for name in (
                "get_operations", "get_providers", "get_history_importers",
                "get_channel_fields", "get_settings_resources", "get_settings_actions",
                "get_summary_profiles", "get_extraction_profiles", "get_skills", "get_hooks",
            )
        }
        self._catalog["get_channel"] = None
        self._channel_cache = None
        self._closed = False
        self._failure = None
        self.handler = None
        self.shutdown_loops = []
        self.source = SimpleNamespace(source_type="sample")

    @property
    def diagnostics(self):
        with self._lock:
            return {"healthy": not self._closed, "last_error": self._failure}

    def set_failure_handler(self, handler):
        with self._lock:
            self.handler = handler
            if self._failure is not None:
                handler(self._failure)

    def die(self, reason="Plugin worker exited", *, notify=True):
        with self._lock:
            self._closed = True
            self._failure = reason
            if notify and self.handler is not None:
                self.handler(reason)

    def get_tools(self):
        return [SampleTool]

    def get_sources(self):
        return [("sample", self.source, SourceSpec("sample", "Sample", domain="timeline"))]

    async def shutdown(self):
        self.shutdown_loops.append(asyncio.get_running_loop())
        self._closed = True


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    config = AppConfig()
    config.plugins.packages["sample"] = PluginSettings(
        trusted=True, source="external", manifest_path=str(tmp_path / "plugin.toml"),
    )
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    tools, sources, instances, refreshes = ToolRegistry(), SourceRegistry(), [], []
    store = PluginConnectionStore(
        runtime_paths=RuntimePaths(base_dir=tmp_path),
        require_package=lambda _: None, authorize_enable=lambda _: None,
    )

    def factory(manifest, connection, context):
        instance = ControlledWorker(manifest, connection, context)
        instances.append(instance)
        return instance

    manager = PluginManager(
        tool_registry=tools, source_registry=sources, connection_store=store,
        search_paths=[], instance_factory=factory,
        request_source_schedule_refresh=lambda: refreshes.append(True),
        connection_disconnector=lambda _: None,
    )
    manager._package_states["sample"] = PluginPackageState(
        manifest=PluginManifest(
            id="sample", name="Sample", version="1.0.0", source="external",
            manifest_path=str(tmp_path / "plugin.toml"),
            contribution_types=["tool", "source"],
            settings_actions=[PluginSettingsActionSpec(
                action_id="login", label="Login", requires_enabled=False,
            )],
        ),
        trusted=True,
    )
    connection = store.create("sample", display_name="One", enabled=True)
    completed = threading.Event()
    handle_failure = manager._handle_worker_failure

    def observe_failure(*args):
        try:
            handle_failure(*args)
        finally:
            completed.set()

    monkeypatch.setattr(manager, "_handle_worker_failure", observe_failure)
    yield SimpleNamespace(
        manager=manager, store=store, connection=connection, tools=tools,
        sources=sources, instances=instances, refreshes=refreshes, completed=completed,
    )
    asyncio.run(manager.shutdown())


async def failure_finished(runtime):
    assert await asyncio.to_thread(runtime.completed.wait, 2), "Failure cleanup did not finish"
    await runtime.manager.drain_shutdowns()


def assert_failed(runtime, connection_id):
    readiness = runtime.store.get_readiness(connection_id)[0]
    assert readiness.status == ConnectionStatus.FAILED
    assert readiness.reason_code == "worker_failed"
    assert runtime.manager.get_connection_plugin(connection_id) is None
    assert f"{connection_id}:sample" not in runtime.tools._tools
    assert runtime.sources.get_source(f"{connection_id}:sample") is None
    assert runtime.manager.get_package("sample").healthy is False


@pytest.mark.asyncio
async def test_failure_callback_revokes_contributions_and_persists_failed_readiness(runtime):
    manager, connection = runtime.manager, runtime.connection
    worker = manager.load_connection(connection.connection_id)
    assert runtime.store.get_readiness(connection.connection_id)[0].status == ConnectionStatus.READY
    refresh_count = len(runtime.refreshes)
    await asyncio.to_thread(worker.die)
    await failure_finished(runtime)
    assert_failed(runtime, connection.connection_id)
    assert manager.iter_loaded_plugins() == []
    state = manager.get_package("sample")
    assert state.loaded is False
    assert state.enabled is True
    assert state.last_error == "Plugin worker exited"
    assert runtime.store.get(connection.connection_id).revision == connection.revision
    assert len(runtime.refreshes) > refresh_count
    assert worker.shutdown_loops == [asyncio.get_running_loop()]


@pytest.mark.asyncio
async def test_failure_preserves_other_connections_and_package_error_until_recovery(runtime):
    manager, first = runtime.manager, runtime.connection
    second = manager.create_connection("sample", display_name="Two", enabled=True)
    first_worker = manager.load_connection(first.connection_id)
    second_worker = manager.get_connection_plugin(second.connection_id)
    second_tool = runtime.tools._tool_instances[f"{second.connection_id}:sample"]
    sessions = manager.settings_service._sessions
    sessions[(first.connection_id, "login", "one")] = first_worker
    sessions[(second.connection_id, "login", "two")] = second_worker
    await asyncio.to_thread(first_worker.die)
    await failure_finished(runtime)
    assert_failed(runtime, first.connection_id)
    assert manager.get_package("sample").loaded
    assert manager.get_connection_plugin(second.connection_id) is second_worker
    assert runtime.tools._tool_instances[f"{second.connection_id}:sample"] is second_tool
    assert runtime.sources.get_source(f"{second.connection_id}:sample") is second_worker.source
    assert manager.connection_readiness(second.connection_id)[0].status == ConnectionStatus.READY
    assert set(manager.settings_service._sessions) == {(second.connection_id, "login", "two")}
    await manager.reload_connection_async(second.connection_id)
    assert manager.get_package("sample").healthy is False
    assert {item.metadata["connection_id"] for item in manager.get_package("sample").contributions} == {
        second.connection_id,
    }
    replacement = await manager.reload_connection_async(first.connection_id)
    assert replacement is not first_worker
    assert manager.get_package("sample").healthy
    assert manager.get_package("sample").last_error is None
    assert manager.connection_readiness(first.connection_id)[0].status == ConnectionStatus.READY


@pytest.mark.asyncio
@pytest.mark.parametrize("lookup", ["load", "readiness", "get", "iterate"])
async def test_dead_proxy_is_not_reused_before_notification_arrives(runtime, lookup):
    manager, connection_id = runtime.manager, runtime.connection.connection_id
    worker = manager.load_connection(connection_id)
    worker.die(notify=False)
    if lookup == "load":
        with pytest.raises(RuntimeError, match="shutdown is pending"):
            manager.load_connection(connection_id)
    elif lookup == "readiness":
        assert manager.connection_readiness(connection_id)[0].status == ConnectionStatus.FAILED
    elif lookup == "get":
        assert manager.get_connection_plugin(connection_id) is None
    else:
        assert manager.iter_loaded_plugins() == []
    await manager.drain_shutdowns()
    assert_failed(runtime, connection_id)
    replacement = manager.load_connection(connection_id)
    assert replacement is not worker
    assert manager.connection_readiness(connection_id)[0].status == ConnectionStatus.READY


@pytest.mark.asyncio
async def test_stale_failure_callback_cannot_remove_replacement(runtime, monkeypatch):
    manager, connection_id = runtime.manager, runtime.connection.connection_id
    worker = manager.load_connection(connection_id)
    entered, release = threading.Event(), threading.Event()
    original = manager._handle_worker_failure

    def delayed(*args):
        entered.set()
        assert release.wait(2)
        original(*args)

    monkeypatch.setattr(manager, "_handle_worker_failure", delayed)
    worker.die()
    assert await asyncio.to_thread(entered.wait, 2)
    try:
        replacement = await manager.reload_connection_async(connection_id)
        tool = runtime.tools._tool_instances[f"{connection_id}:sample"]
    finally:
        release.set()
    await failure_finished(runtime)
    assert manager.get_connection_plugin(connection_id) is replacement
    assert runtime.tools._tool_instances[f"{connection_id}:sample"] is tool
    assert manager.connection_readiness(connection_id)[0].status == ConnectionStatus.READY
    assert manager.get_package("sample").healthy
    assert replacement.shutdown_loops == []


@pytest.mark.asyncio
async def test_death_during_authorization_cannot_return_the_cached_proxy(runtime, monkeypatch):
    manager, connection_id = runtime.manager, runtime.connection.connection_id
    worker = manager.load_connection(connection_id)
    authorize = manager._authorize_connection

    def die_during_authorization(connection):
        authorize(connection)
        worker.die(notify=False)

    monkeypatch.setattr(manager, "_authorize_connection", die_during_authorization)
    with pytest.raises(RuntimeError, match="shutdown is pending"):
        manager.load_connection(connection_id)
    await manager.drain_shutdowns()
    assert_failed(runtime, connection_id)


@pytest.mark.asyncio
async def test_transport_callback_does_not_wait_for_lifecycle_lock(runtime):
    manager, connection_id = runtime.manager, runtime.connection.connection_id
    worker = manager.load_connection(connection_id)
    with manager._lifecycle_write_lock:
        transport = threading.Thread(target=worker.die, daemon=True)
        transport.start()
        transport.join(timeout=1)
        assert not transport.is_alive(), "Failure callback blocked the transport thread"
    await failure_finished(runtime)
    assert_failed(runtime, connection_id)


def test_failure_cleanup_without_a_runtime_loop(runtime):
    manager, connection_id = runtime.manager, runtime.connection.connection_id
    worker = manager.load_connection(connection_id)
    assert manager._runtime_loop is None
    worker.die()
    assert runtime.completed.wait(2)
    asyncio.run(manager.drain_shutdowns())
    assert_failed(runtime, connection_id)
    assert len(worker.shutdown_loops) == 1
    assert manager.load_connection(connection_id) is not worker


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before_watch", "during_registration"])
async def test_worker_death_during_load_never_publishes_ready(runtime, monkeypatch, when):
    manager, connection_id = runtime.manager, runtime.connection.connection_id
    if when == "before_watch":
        manager._configure_instance = lambda _, worker: worker.die(notify=False)
    else:
        original = manager._contribution_registrar.register

        def die_after_registration(**kwargs):
            contributions = original(**kwargs)
            kwargs["plugin_instance"].die()
            return contributions

        monkeypatch.setattr(manager._contribution_registrar, "register", die_after_registration)
    with pytest.raises(RuntimeError, match="Plugin worker exited"):
        manager.load_connection(connection_id)
    await failure_finished(runtime)
    assert_failed(runtime, connection_id)
    assert not manager.get_package("sample").loaded


@pytest.mark.asyncio
async def test_registration_error_is_not_reclassified_by_its_cleanup(runtime, monkeypatch):
    manager, connection_id = runtime.manager, runtime.connection.connection_id

    def reject_registration(**kwargs):
        raise ValueError("Invalid contribution")

    unload = manager.unload_connection

    def close_immediately(connection_id):
        instance = manager._plugin_instances[connection_id]
        unload(connection_id)
        instance._closed = True

    monkeypatch.setattr(manager._contribution_registrar, "register", reject_registration)
    monkeypatch.setattr(manager, "unload_connection", close_immediately)
    with pytest.raises(ValueError, match="Invalid contribution"):
        manager.load_connection(connection_id)
    await manager.drain_shutdowns()
    assert manager.connection_readiness(connection_id)[0].reason_code == "load_failed"
    assert manager.get_package("sample").last_error == "Invalid contribution"


@pytest.mark.asyncio
async def test_failed_connection_can_be_disabled_and_enabled_with_a_new_worker(runtime):
    manager, connection = runtime.manager, runtime.connection
    worker = manager.load_connection(connection.connection_id)
    worker.die()
    await failure_finished(runtime)
    disabled = await asyncio.to_thread(
        manager.update_connection, connection.connection_id,
        expected_revision=connection.revision, enabled=False,
    )
    assert manager.connection_readiness(connection.connection_id)[0].status == ConnectionStatus.DISABLED
    assert manager.get_package("sample").healthy
    await asyncio.to_thread(
        manager.update_connection, connection.connection_id,
        expected_revision=disabled.revision, enabled=True,
    )
    assert manager.get_connection_plugin(connection.connection_id) is not worker
    assert manager.connection_readiness(connection.connection_id)[0].status == ConnectionStatus.READY


@pytest.mark.asyncio
async def test_setup_worker_failure_is_observed_and_replaced(runtime):
    manager, connection = runtime.manager, runtime.connection
    runtime.store.update(connection.connection_id, expected_revision=0, enabled=False)
    worker = manager.setup_connection(connection.connection_id)
    assert runtime.tools._tools == {}
    worker.die()
    await failure_finished(runtime)
    assert_failed(runtime, connection.connection_id)
    replacement = manager.setup_connection(connection.connection_id)
    assert replacement is not worker
    assert manager.connection_readiness(connection.connection_id)[0].reason_code == "enable_required"
    assert manager.get_package("sample").healthy


@pytest.mark.asyncio
async def test_explicit_shutdown_and_late_disconnected_callback_are_inert(runtime):
    manager, connection = runtime.manager, runtime.connection
    worker = manager.load_connection(connection.connection_id)
    await asyncio.to_thread(
        manager.disconnect_connection, connection.connection_id, expected_revision=0,
    )
    worker.handler("Late failure")
    await failure_finished(runtime)
    assert runtime.store.list() == []
    assert manager.iter_loaded_plugins() == []
    assert manager.get_package("sample").healthy
