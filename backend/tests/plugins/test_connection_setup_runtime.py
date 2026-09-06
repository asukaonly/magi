"""Disabled setup sessions use real workers without publishing contributions."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.manager import PluginManager
from magi.plugins.operation_authorization import InstalledOperationAuthorizer, build_host_invocation
from magi.plugins.process_runtime import ProcessPluginProxy
from magi.plugins.sources import SourceRegistry
from magi.agent.background import BackgroundTaskStore
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths


MANIFEST = '''
[plugin]
id = "setup-test"
name = "Setup test"
version = "0.2.0"
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
entry_module = "plugin"
entry_class = "SetupPlugin"
contribution_types = ["tool", "source"]

[[plugin.permissions.capabilities]]
capability = "network"
scope = ["login.example.test"]

[[plugin.settings_actions]]
action_id = "login"
label = "Login"
requires_enabled = false

[[plugin.settings_actions]]
action_id = "send"
label = "Send"
requires_enabled = true

[[plugin.settings_resources]]
resource_name = "status"
requires_enabled = false
'''

PLUGIN = '''
import asyncio, os
from magi_plugin_sdk import Plugin
from magi_plugin_sdk.sources import Source, SourceSpec
from magi_plugin_sdk.tools import Tool, ToolResult, ToolSchema

class SampleTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(name="sample", description="Read", category="test",
            effect_class="read_only", effect_replay_policy="read_only")
    async def execute(self, parameters, context):
        return ToolResult(success=True, data={"pid": os.getpid()})

class SampleSource(Source):
    source_type = "setup_source"
    async def collect_items(self, context):
        raise AssertionError("Setup must not collect")
    async def build_output(self, item):
        raise NotImplementedError

class SetupPlugin(Plugin):
    def configure(self, **kwargs):
        super().configure(**kwargs)
        self.session = None
        self._record("start")
    def _record(self, event):
        with (self.context.state_dir / "workers.log").open("a") as stream:
            stream.write(f"{event}:{os.getpid()}\\n")
    def get_tools(self):
        return [SampleTool]
    def get_sources(self):
        return [("source", SampleSource(), SourceSpec("source", "Source", domain="timeline"))]
    def read_settings_resource(self, resource_name):
        return {"pid": os.getpid(), "session": self.session}
    async def start_settings_action(self, action_id, *, session_id, field_values=None):
        self.session = session_id
        return {"status": "pending", "data": {"pid": os.getpid(), "session": self.session}}
    async def poll_settings_action(self, action_id, *, session_id, field_values=None):
        assert self.session == session_id
        self.context.credentials.set("token", "login-token")
        return {"status": "succeeded", "data": {"pid": os.getpid(), "session": self.session}}
    async def cancel_settings_action(self, action_id, *, session_id):
        self.session = None
        return {"status": "cancelled"}
    async def shutdown(self):
        while (self.context.state_dir / "hold-shutdown").exists():
            await asyncio.sleep(0.01)
        self._record("stop")
'''


@pytest.fixture
def setup_runtime(tmp_path, monkeypatch, runtime_paths_with_schema):
    package = tmp_path / "package"
    package.mkdir()
    path = package / "plugin.toml"
    path.write_text(MANIFEST)
    (package / "plugin.py").write_text(PLUGIN)
    config = AppConfig()
    config.plugins.packages["setup-test"] = PluginSettings(
         trusted=True, source="external", manifest_path=str(path),
        consented_capabilities=[{"capability": "network", "scope": ["login.example.test"]}],
    )
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    tools, sources, configured = ToolRegistry(), SourceRegistry(), []
    tools.bind_tool_effect_ledger(BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)))
    store = PluginConnectionStore(
        runtime_paths=RuntimePaths(base_dir=tmp_path),
        require_package=lambda plugin_id: manager._require_connection_package(plugin_id),
        authorize_enable=lambda connection: manager._authorize_connection(connection),
        validate_settings=lambda _: None,
    )

    def configure_instance(manifest, instance):
        assert instance.manifest is manifest
        assert f"{instance.connection_id}:sample" not in tools._tools
        configured.append(instance)

    manager = PluginManager(
        tool_registry=tools, source_registry=sources, search_paths=[package],
        request_source_schedule_refresh=lambda: None,
        connection_store=store, configure_instance=configure_instance,
        connection_disconnector=lambda _: None, content_clearer=lambda *_: None,
    )
    manager.scan(persist_discovery=False)
    manager.operation_registry._authorize = InstalledOperationAuthorizer(
        get_package=manager.get_package, connection_store=store, config_provider=lambda: config)
    manager.operation_registry._publish_progress = AsyncMock()
    connection = manager.create_connection("setup-test", display_name="Account")
    runtime = SimpleNamespace(manager=manager, connection=connection, tools=tools, sources=sources,
                              config=config, configured=configured, store=store, path=path)
    yield runtime
    asyncio.run(manager.shutdown())


@pytest.mark.asyncio
async def test_disabled_login_retains_real_worker_and_publishes_no_contributions(setup_runtime):
    runtime = setup_runtime
    manager, connection = runtime.manager, runtime.connection
    identity = build_host_invocation(connection, trigger="user")
    started = await manager.start_plugin_settings_action(connection.connection_id, "login", identity=identity)
    assert started.result.status == "pending", started.result
    worker = manager._setup_instances[connection.connection_id]
    assert isinstance(worker, ProcessPluginProxy)
    assert started.result.data["pid"] != os.getpid()
    assert manager.get_connection_plugin(connection.connection_id) is None
    assert manager.iter_loaded_plugins() == []
    assert not manager.get_package(connection.plugin_id).loaded
    assert not manager.get_package(connection.plugin_id).enabled
    assert f"{connection.connection_id}:sample" not in runtime.tools._tools
    assert runtime.tools.list_tools() == []
    assert runtime.tools.get_all_tools_info() == []
    assert runtime.tools.export_to_claude_format() == []
    assert runtime.sources.snapshot_user_content_clear_targets() == ()
    assert runtime.configured == [worker]
    resource = await manager.read_plugin_settings_resource(connection.connection_id, "status")
    assert resource.data["session"] == started.session_id
    polled = await manager.poll_plugin_settings_action(
        connection.connection_id, "login", identity=build_host_invocation(connection, trigger="user"),
        session_id=started.session_id)
    assert polled.result.status == "succeeded", polled.result
    assert polled.result.data["pid"] == started.result.data["pid"]
    assert runtime.store.context(connection.connection_id).credentials.get("token") == "login-token"
    assert await asyncio.to_thread(manager.setup_connection, connection.connection_id) is worker
    model_result = await manager.operation_registry.invoke(
        connection.connection_id, "settings:login:start",
        {"session_id": "model-session", "field_values": {}},
        identity=build_host_invocation(runtime.store.get(connection.connection_id), trigger="model"))
    assert model_result.status == "failed"


@pytest.mark.asyncio
async def test_setup_requires_manifest_action_and_live_consent_before_import(setup_runtime):
    runtime = setup_runtime
    manager, connection = runtime.manager, runtime.connection
    identity = build_host_invocation(connection, trigger="user")
    with pytest.raises(PermissionError, match="enabled"):
        await manager.start_plugin_settings_action(connection.connection_id, "send", identity=identity)
    with pytest.raises(KeyError):
        await manager.start_plugin_settings_action(connection.connection_id, "undeclared", identity=identity)
    assert not runtime.configured
    runtime.config.plugins.packages[connection.plugin_id].consented_capabilities = []
    with pytest.raises(PermissionError, match="consent"):
        await asyncio.to_thread(manager.setup_connection, connection.connection_id)
    assert not runtime.configured
    assert not (runtime.store.root / "instances" / connection.connection_id).exists()


@pytest.mark.asyncio
async def test_enable_drains_setup_before_new_worker_and_disable_updates_projection(setup_runtime):
    runtime = setup_runtime
    manager, connection = runtime.manager, runtime.connection
    setup = await asyncio.to_thread(manager.setup_connection, connection.connection_id)
    old_pid = (await setup.read_settings_resource_async("status"))["pid"]
    enabled = await asyncio.to_thread(manager.update_connection, connection.connection_id,
                                     expected_revision=connection.revision, enabled=True)
    active = manager.get_connection_plugin(connection.connection_id)
    assert active is not None and active is not setup
    assert setup.diagnostics["exit_code"] is not None
    assert connection.connection_id not in manager._setup_instances
    assert len(runtime.configured) == 2
    assert f"{connection.connection_id}:sample" in runtime.tools._tools
    assert manager.get_package(connection.plugin_id).enabled
    log = runtime.store.context(connection.connection_id).state_dir / "workers.log"
    events = log.read_text().splitlines()
    assert events[0] == f"start:{old_pid}"
    assert events[1] == f"stop:{old_pid}"
    assert events[2].startswith("start:")
    disabled = await asyncio.to_thread(manager.update_connection, connection.connection_id,
                                      expected_revision=enabled.revision, enabled=False)
    assert not disabled.enabled
    assert not manager.get_package(connection.plugin_id).enabled
    assert not manager.get_package(connection.plugin_id).loaded
    assert not runtime.tools._tools


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["disable", "disconnect", "clear", "shutdown", "global_clear"])
async def test_every_teardown_drains_setup_and_revokes_session_bindings(setup_runtime, action):
    runtime = setup_runtime
    manager, connection = runtime.manager, runtime.connection
    started = await manager.start_plugin_settings_action(
        connection.connection_id, "login", identity=build_host_invocation(connection, trigger="user"))
    assert started.result.status == "pending", started.result
    setup = manager._setup_instances[connection.connection_id]
    if action == "disable":
        await asyncio.to_thread(manager.update_connection, connection.connection_id,
                                expected_revision=connection.revision, enabled=False)
    elif action == "disconnect":
        await asyncio.to_thread(manager.disconnect_connection, connection.connection_id,
                                expected_revision=connection.revision)
    elif action == "clear":
        await asyncio.to_thread(manager.clear_connection_content, connection.connection_id,
                                expected_revision=connection.revision)
    elif action == "shutdown":
        await manager.shutdown()
    else:
        targets = await asyncio.to_thread(manager.snapshot_user_content_clear_targets)
        assert targets.temporary_plugin_ids == {connection.connection_id}
        for connection_id, temporary, _ in targets.plugins:
            await temporary.shutdown()
            manager.release_temporary_user_content_clear_target(connection_id)
    assert setup.diagnostics["exit_code"] is not None
    assert not manager._setup_instances
    assert not manager._pending_plugin_shutdowns
    assert not manager.settings_service._sessions
    assert not manager.operation_registry._entries
    assert not runtime.tools._tools


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_host_configuration_failure_drains_real_worker(setup_runtime, enabled):
    runtime = setup_runtime
    observed = []

    def reject(manifest, instance):
        observed.append(instance)
        raise ValueError("Host broker configuration failed")

    runtime.manager._configure_instance = reject
    if enabled:
        runtime.store.update(runtime.connection.connection_id,
                             expected_revision=runtime.connection.revision, enabled=True)
    loader = runtime.manager.load_connection if enabled else runtime.manager.setup_connection
    with pytest.raises(ValueError, match="broker configuration"):
        await asyncio.to_thread(loader, runtime.connection.connection_id)
    await runtime.manager.drain_shutdowns()
    assert len(observed) == 1
    assert observed[0].diagnostics["exit_code"] is not None
    assert not runtime.manager._setup_instances
    assert runtime.manager.get_connection_plugin(runtime.connection.connection_id) is None
    assert not runtime.tools._tools


def test_scan_reads_settings_only_from_explicit_connection(setup_runtime):
    runtime = setup_runtime
    with pytest.raises(ValueError, match="settings"):
        runtime.config.plugins.packages["setup-test"].settings = {"old": "rejected"}
    runtime.manager.scan(persist_discovery=False)
    state = runtime.manager.get_package("setup-test")
    assert not state.enabled
    assert state.current_settings == {}
    runtime.store.update(runtime.connection.connection_id, expected_revision=runtime.connection.revision,
                         settings={"directory": "/selected"})
    runtime.manager.scan(persist_discovery=False)
    assert runtime.manager.get_package("setup-test").current_settings == {"directory": "/selected"}


def test_library_access_never_queries_connection_store(setup_runtime, monkeypatch):
    from magi_plugin_sdk import PluginManifest, PluginPackageState

    runtime = setup_runtime
    library = PluginManifest(id="shared-lib", name="Library", version="0.2.0", kind="library")
    runtime.manager._package_states[library.plugin_id] = PluginPackageState(manifest=library, trusted=True)
    runtime.manager.load_plugin(library.plugin_id)
    assert runtime.manager.get_package(library.plugin_id).loaded
    monkeypatch.setattr("magi.plugins.installation.PluginInstallationMixin.uninstall_plugin", lambda *args: [])
    assert runtime.manager.uninstall_plugin(library.plugin_id) == []


@pytest.mark.asyncio
async def test_pending_real_setup_shutdown_blocks_replacement(setup_runtime):
    runtime = setup_runtime
    connection_id = runtime.connection.connection_id
    worker = await asyncio.to_thread(runtime.manager.setup_connection, connection_id)
    hold = worker.context.state_dir / "hold-shutdown"
    hold.touch()
    updating = asyncio.create_task(asyncio.to_thread(
        runtime.manager.update_connection, connection_id,
        expected_revision=runtime.connection.revision, enabled=True))
    try:
        for _ in range(200):
            if connection_id in runtime.manager._pending_plugin_shutdowns:
                break
            await asyncio.sleep(0.01)
        assert connection_id in runtime.manager._pending_plugin_shutdowns
        assert not updating.done()
        assert len(runtime.configured) == 1
        with pytest.raises(RuntimeError, match="shutdown is pending"):
            await asyncio.to_thread(runtime.manager.setup_connection, connection_id)
    finally:
        hold.unlink()
        await asyncio.wait_for(updating, 5)
    assert worker.diagnostics["exit_code"] is not None
    assert len(runtime.configured) == 2


@pytest.mark.asyncio
async def test_connection_readiness_tracks_each_account_and_actual_registration(setup_runtime):
    from magi_plugin_sdk.runtime import CapabilityReadiness, ConnectionStatus

    runtime = setup_runtime
    manager = runtime.manager
    first = await asyncio.to_thread(manager.update_connection, runtime.connection.connection_id,
                                    expected_revision=runtime.connection.revision, enabled=True)
    second = await asyncio.to_thread(manager.create_connection, first.plugin_id, display_name="Second", enabled=True)
    assert manager.connection_readiness(first.connection_id)[0].status == ConnectionStatus.READY
    assert runtime.store.get_readiness(second.connection_id)[0].status == ConnectionStatus.READY
    await manager.unload_connection_async(first.connection_id)
    assert manager.connection_readiness(first.connection_id)[0].reason_code == "not_loaded"
    assert manager.connection_readiness(second.connection_id)[0].status == ConnectionStatus.READY
    scoped = CapabilityReadiness(connection_id=second.connection_id, capability_id="network",
                                 status=ConnectionStatus.AUTH_REQUIRED, reason_code="consent_expired")
    runtime.store.set_readiness(second.connection_id, [scoped], expected_revision=second.revision)
    assert scoped in manager.connection_readiness(second.connection_id)
    await asyncio.to_thread(manager.update_connection, first.connection_id,
                            expected_revision=first.revision, enabled=False)
    assert manager.get_package(first.plugin_id).enabled
    assert manager.connection_readiness(first.connection_id)[0].status == ConnectionStatus.DISABLED
    assert manager.connection_readiness(second.connection_id)[0].status == ConnectionStatus.READY


@pytest.mark.asyncio
async def test_setup_readiness_requires_manifest_credentials_and_failure_is_sanitized(setup_runtime):
    from magi_plugin_sdk.contracts import ExtensionFieldSpec
    from magi_plugin_sdk.runtime import ConnectionStatus

    runtime = setup_runtime
    manager = runtime.manager
    connection_id = runtime.connection.connection_id
    manager.get_package(runtime.connection.plugin_id).manifest.settings_fields = [
        ExtensionFieldSpec(key="token", label="Token", type="secret", required=True)]
    await asyncio.to_thread(manager.setup_connection, connection_id)
    state = manager.connection_readiness(connection_id)[0]
    assert state.status == ConnectionStatus.AUTH_REQUIRED
    assert state.reason_code == "credentials_required"
    assert runtime.store.get_readiness(connection_id) == [state]
    runtime.store.context(connection_id).credentials.set("token", "secret-token")
    assert manager.connection_readiness(connection_id)[0].reason_code == "enable_required"
    await manager.unload_connection_async(connection_id)

    def reject(*_):
        raise ValueError("sensitive-token-value")

    manager._configure_instance = reject
    with pytest.raises(ValueError, match="sensitive-token-value"):
        await asyncio.to_thread(manager.setup_connection, connection_id)
    await manager.drain_shutdowns()
    failed = manager.connection_readiness(connection_id)[0]
    assert failed.status == ConnectionStatus.FAILED
    assert failed.reason_code == "setup_start_failed"
    assert "sensitive-token-value" not in failed.model_dump_json()


@pytest.mark.asyncio
async def test_runtime_builder_binds_early_hooks_and_configures_setup_and_active_workers(setup_runtime, monkeypatch):
    from magi.hooks.registry import HookRegistry
    from magi.plugins.manager import build_plugin_runtime

    runtime = setup_runtime
    hooks, configured = HookRegistry(), []
    runtime.path.write_text(MANIFEST.replace('["tool", "source"]', '["tool", "source", "hook"]'))
    runtime.path.with_name("plugin.py").write_text(PLUGIN + '''
    def get_hooks(self):
        from magi_plugin_sdk.hooks import HookDecision, HookEventType
        async def before_tool(context):
            return HookDecision.continue_()
        return [(HookEventType.PRE_TOOL_USE, before_tool, None)]
''')
    monkeypatch.setattr("magi.plugins.manager._resolve_search_paths", lambda: [runtime.path.parent])
    bindings = build_plugin_runtime(
        tool_registry=runtime.tools, source_registry=runtime.sources,
        request_source_schedule_refresh=lambda: None, activate_enabled=False,
        connection_store=runtime.store,
        configure_instance=lambda manifest, instance: configured.append((manifest, instance)),
        hook_registry_provider=lambda: hooks,
    )
    manager = bindings.plugin_manager
    try:
        setup = await asyncio.to_thread(manager.setup_connection, runtime.connection.connection_id)
        assert hooks.total() == 0
        await asyncio.to_thread(manager.update_connection, runtime.connection.connection_id,
                                expected_revision=runtime.connection.revision, enabled=True)
        assert setup.diagnostics["exit_code"] is not None
        assert hooks.total() == 1
        assert len(configured) == 2
        assert configured[1][1] is manager.get_connection_plugin(runtime.connection.connection_id)
    finally:
        await manager.shutdown()
    assert hooks.total() == 0


@pytest.mark.asyncio
async def test_revoked_consent_closes_retained_setup_and_invalidates_sessions(setup_runtime):
    runtime = setup_runtime
    connection = runtime.connection
    manager = runtime.manager
    await manager.start_plugin_settings_action(connection.connection_id, "login",
        identity=build_host_invocation(connection, trigger="user"))
    worker = manager._setup_instances[connection.connection_id]
    runtime.config.plugins.packages[connection.plugin_id].consented_capabilities = []
    with pytest.raises(PermissionError, match="consent"):
        await asyncio.to_thread(manager.setup_connection, connection.connection_id)
    await manager.drain_shutdowns()
    assert worker.diagnostics["exit_code"] is not None
    assert not manager._setup_instances
    assert not manager.settings_service._sessions
    assert not manager.operation_registry._entries
