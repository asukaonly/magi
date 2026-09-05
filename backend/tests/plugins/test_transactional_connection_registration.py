"""Connection ownership, transactional registration, and drained lifecycle behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import pytest

from magi.config.models import AppConfig
from magi.hooks.contracts import HookEventType
from magi.hooks.registry import HookRegistry
from magi.plugins.contribution_registration import PluginContributionRegistrar
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.discovery import load_plugin_manifest
from magi.plugins.history_importers import HistoryImporterRegistry
from magi.plugins.manager import PluginManager
from magi.plugins.operations import PluginOperationRegistry
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths
from magi_plugin_sdk import Plugin, PluginManifest, PluginPackageState
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.history_imports import HistoryImporterSpec
from magi_plugin_sdk.runtime import PluginConnection
from magi_plugin_sdk.sensors import SensorSpec
from magi_plugin_sdk.tools import Tool, ToolResult, ToolSchema


class SampleTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(
            name="sample",
            description="Sample read",
            category="test",
            effect_class="read_only",
            effect_replay_policy="read_only",
        )

    async def execute(self, parameters, context):
        return ToolResult(success=True, data={"ok": True})


class SamplePlugin(Plugin):
    def get_tools(self):
        return [SampleTool]

    def get_operations(self):
        return []

    def get_providers(self):
        return []


def manifest(plugin_id="a", kinds=("tool",), **kwargs):
    return PluginManifest(
        id=plugin_id,
        name=plugin_id,
        version="1.0.0",
        contribution_types=list(kinds),
        source="external",
        **kwargs,
    )


def configured(tmp_path, plugin_id="a", connection_id="a-one", kinds=("tool",), plugin=None):
    package = manifest(plugin_id, kinds)
    connection = PluginConnection(
        connection_id=connection_id, plugin_id=plugin_id, display_name=connection_id, enabled=True
    )
    context = PluginContext(
        connection=connection,
        state_dir=tmp_path / connection_id / "state",
        resources_dir=tmp_path / connection_id / "resources",
        credentials=SimpleNamespace(),
    )
    instance = plugin or SamplePlugin()
    instance.configure(manifest=package, connection=connection, context=context)
    return package, instance


def registrar(hooks=None, **kwargs):
    tools, sensors = ToolRegistry(), SensorRegistry()
    operations = PluginOperationRegistry(tools, get_connection=lambda _: None)
    return (
        PluginContributionRegistrar(
            tool_registry=tools,
            sensor_registry=sensors,
            hook_registry_provider=lambda: hooks,
            operation_registrar=operations,
            **kwargs,
        ),
        tools,
        sensors,
    )


def register(reg, package, plugin):
    return reg.register(
        plugin_id=package.plugin_id,
        connection_id=plugin.connection_id,
        manifest=package,
        plugin_instance=plugin,
    )


def test_tool_collision_does_not_overwrite_owner_or_remove_replacement():
    tools = ToolRegistry()
    old = tools.register(SampleTool, owner_id="a")
    original = tools._tool_instances["sample"]
    with pytest.raises(ValueError, match="already registered"):
        tools.register(SampleTool, owner_id="b")
    assert tools._tool_instances["sample"] is original
    assert tools.unregister("sample", owner_id="b") is False
    assert tools.unregister("sample") is False
    old()
    tools.register(SampleTool, owner_id="b")
    replacement = tools._tool_instances["sample"]
    old()
    assert tools._tool_instances["sample"] is replacement
    assert tools._category_index["test"] == ["sample"]


def test_sensor_collision_and_stale_disposer_are_owner_safe():
    sensors = SensorRegistry()
    original = object()
    old = sensors.register("a", "same", original, SensorSpec("same", "Same"))
    with pytest.raises(ValueError, match="already registered"):
        sensors.register("b", "same", object(), SensorSpec("same", "Same"))
    assert sensors.unregister("same", plugin_id="b") is False
    assert sensors.get_sensor("same") is original
    old()
    replacement = object()
    sensors.register("b", "same", replacement, SensorSpec("same", "Same"))
    old()
    assert sensors.get_sensor("same") is replacement


def test_history_importer_disposer_cannot_remove_replacement():
    registry = HistoryImporterRegistry()
    spec = HistoryImporterSpec(
        importer_id="history",
        display_name="History",
        accepted_extensions=[".json"],
        format_version="1",
    )
    importer = SimpleNamespace(parse=lambda paths: None)
    old = registry.register(plugin_id="a", importer_id="history", importer=importer, spec=spec)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(plugin_id="a", importer_id="history", importer=importer, spec=spec)
    old()
    replacement = SimpleNamespace(parse=lambda paths: None)
    registry.register(plugin_id="a", importer_id="history", importer=replacement, spec=spec)
    old()
    assert registry.get("a", "history").importer is replacement


def test_connections_share_local_tool_names_without_collision(tmp_path):
    reg, tools, _ = registrar()
    first, a = configured(tmp_path)
    second, b = configured(tmp_path, connection_id="a-two")
    register(reg, first, a)
    register(reg, second, b)
    assert set(tools._tools) == {"a-one:sample", "a-two:sample"}
    reg.unregister("a-one")
    assert set(tools._tools) == {"a-two:sample"}
    with pytest.raises(ValueError, match="already registered"):
        register(reg, second, b)
    assert set(tools._tools) == {"a-two:sample"}


@pytest.mark.parametrize("kinds", [(), ("tool", "sensor")])
def test_declaration_mismatch_publishes_nothing(tmp_path, kinds):
    reg, tools, sensors = registrar()
    package, plugin = configured(tmp_path, kinds=kinds)
    with pytest.raises(ValueError, match="declaration mismatch"):
        register(reg, package, plugin)
    assert tools._tools == {}
    assert sensors.list_specs() == []


def test_late_hook_failure_rolls_back_all_contributions(tmp_path):
    class LatePlugin(SamplePlugin):
        def get_sensors(self):
            return [("source", object(), SensorSpec("source", "Source"))]

        def get_hooks(self):
            async def good(context):
                return None

            return [(next(iter(HookEventType)).value, good, None), ("invalid", good, None)]

    hooks = HookRegistry()
    reg, tools, sensors = registrar(hooks=hooks)
    stable, stable_plugin = configured(tmp_path, plugin_id="b", connection_id="b-one")
    register(reg, stable, stable_plugin)
    package, plugin = configured(tmp_path, kinds=("tool", "sensor", "hook"), plugin=LatePlugin())
    with pytest.raises(ValueError):
        register(reg, package, plugin)
    assert set(tools._tools) == {"b-one:sample"}
    assert sensors.list_specs() == []
    assert hooks.total() == 0
    reg.unregister("a-one")
    assert set(tools._tools) == {"b-one:sample"}


def test_get_hooks_error_propagates_without_registration(tmp_path):
    class Broken(SamplePlugin):
        def get_hooks(self):
            raise RuntimeError("Broken hook declaration")

    reg, tools, _ = registrar()
    package, plugin = configured(tmp_path, plugin=Broken())
    with pytest.raises(RuntimeError, match="Broken hook"):
        register(reg, package, plugin)
    assert tools._tools == {}


def test_declared_skill_requires_a_usable_registrar(tmp_path):
    class SkillPlugin(SamplePlugin):
        def get_skills(self):
            return [("demo", tmp_path)]

    reg, tools, _ = registrar()
    package, plugin = configured(tmp_path, kinds=("tool", "skill"), plugin=SkillPlugin())
    with pytest.raises(RuntimeError, match="skill registry is unavailable"):
        register(reg, package, plugin)
    assert tools._tools == {}


def make_manager(tmp_path, monkeypatch, plugin_type=SamplePlugin):
    config = AppConfig()
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    tools, sensors, instances = ToolRegistry(), SensorRegistry(), []

    def factory(package, connection, context):
        instance = plugin_type()
        instance.configure(manifest=package, connection=connection, context=context)
        instances.append(instance)
        return instance

    store = PluginConnectionStore(
        runtime_paths=RuntimePaths(base_dir=tmp_path),
        require_package=lambda _: None,
        authorize_enable=lambda _: None,
    )
    manager = PluginManager(
        tool_registry=tools,
        sensor_registry=sensors,
        search_paths=[],
        request_sensor_schedule_refresh=lambda: None,
        connection_store=store,
        instance_factory=factory,
    )
    manager._package_states["a"] = PluginPackageState(
        manifest=manifest(), trusted=True, enabled=True
    )
    connection = store.create("a", display_name="One", enabled=True)
    return manager, connection, tools, instances


@pytest.mark.asyncio
async def test_async_reload_waits_for_pending_shutdown(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(SamplePlugin):
        async def shutdown(self):
            entered.set()
            await release.wait()

    manager, connection, tools, instances = make_manager(tmp_path, monkeypatch, Slow)
    manager.load_connection(connection.connection_id)
    old = instances[0]
    reloading = asyncio.create_task(manager.reload_connection_async(connection.connection_id))
    await asyncio.wait_for(entered.wait(), 2)
    assert tools._tools == {}
    assert len(instances) == 1
    with pytest.raises(RuntimeError, match="shutdown is pending"):
        manager.load_connection(connection.connection_id)
    release.set()
    replacement = await reloading
    assert replacement is not old
    assert len(instances) == 2
    await manager.shutdown()


@pytest.mark.asyncio
async def test_failed_startup_instance_drains_before_retry(tmp_path, monkeypatch):
    closed = asyncio.Event()

    class Broken(SamplePlugin):
        def get_hooks(self):
            raise ValueError("Late startup failure")

        async def shutdown(self):
            closed.set()

    manager, connection, tools, instances = make_manager(tmp_path, monkeypatch, Broken)
    with pytest.raises(ValueError, match="startup failure"):
        manager.load_connection(connection.connection_id)
    assert tools._tools == {}
    assert manager.get_connection_plugin(connection.connection_id) is None
    await manager.drain_shutdowns()
    assert closed.is_set()
    assert manager.get_package("a").healthy is False


@pytest.mark.asyncio
async def test_failed_shutdown_blocks_replacement(tmp_path, monkeypatch):
    class BrokenShutdown(SamplePlugin):
        async def shutdown(self):
            raise ValueError("Shutdown failed")

    manager, connection, _, instances = make_manager(tmp_path, monkeypatch, BrokenShutdown)
    manager.load_connection(connection.connection_id)
    manager.unload_connection(connection.connection_id)
    with pytest.raises(RuntimeError, match="replacement is blocked"):
        await manager.drain_shutdowns()
    with pytest.raises(ValueError, match="Shutdown failed"):
        manager.load_connection(connection.connection_id)
    assert len(instances) == 1


@pytest.mark.asyncio
async def test_multiple_connections_and_ambiguous_package_lookup(tmp_path, monkeypatch):
    manager, first, tools, _ = make_manager(tmp_path, monkeypatch)
    second = manager.connection_store.create("a", display_name="Two", enabled=True)
    manager.load_plugin("a")
    assert len(manager.iter_loaded_plugins()) == 2
    with pytest.raises(ValueError, match="explicit connection"):
        manager.get_loaded_plugin("a")
    assert len(tools._tools) == 2
    await manager.unload_connection_async(first.connection_id)
    assert manager.get_loaded_plugin("a") is manager.get_connection_plugin(second.connection_id)
    await manager.shutdown()


def test_no_settings_to_connection_migration(tmp_path, monkeypatch):
    manager, first, tools, instances = make_manager(tmp_path, monkeypatch)
    manager.connection_store.disconnect(first.connection_id, expected_revision=0)
    manager.get_package("a").current_settings = {"account": "legacy"}
    manager.load_plugin("a")
    assert manager.connection_store.list() == []
    assert instances == []
    assert tools._tools == {}


@pytest.mark.parametrize(
    "sdk,protocol,error",
    [("0.3.0", 2, "requires SDK"), ("0.2.0", 1, "Unsupported plugin protocol")],
)
def test_runtime_version_rejected_before_instantiation(tmp_path, monkeypatch, sdk, protocol, error):
    manager, connection, _, instances = make_manager(tmp_path, monkeypatch)
    state = manager.get_package("a")
    state.manifest = state.manifest.model_copy(
        update={"min_sdk_version": sdk, "protocol_version": protocol}
    )
    with pytest.raises(ValueError, match=error):
        manager.load_connection(connection.connection_id)
    assert instances == []


@pytest.mark.parametrize("missing", ["protocol_version", "min_sdk_version"])
def test_disk_manifest_requires_explicit_runtime_contract(tmp_path, missing):
    fields = {"protocol_version": "2", "min_sdk_version": '"0.2.0"'}
    fields.pop(missing)
    path = tmp_path / "plugin.toml"
    path.write_text(
        '[plugin]\nid="sample"\nname="Sample"\nversion="1.0.0"\n'
        + "\n".join(f"{key}={value}" for key, value in fields.items())
    )
    with pytest.raises(ValueError, match=missing):
        load_plugin_manifest(path, source="external")


def test_disk_manifest_cannot_claim_builtin_origin(tmp_path):
    path = tmp_path / "plugin.toml"
    path.write_text(
        '[plugin]\nid="sample"\nname="Sample"\nversion="1.0.0"\n'
        'protocol_version=2\nmin_sdk_version="0.2.0"\nsource="builtin"\n'
    )
    assert load_plugin_manifest(path, source="external").source == "external"


def test_packaged_skill_loads_through_real_host_loader_and_disposes(tmp_path):
    from magi.plugins.skills import PluginSkillRegistry
    from magi.skills.indexer import SkillIndexer
    from magi.skills.loader import SkillLoader

    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A test skill\n---\nUse the source evidence.\n"
    )
    tools, sensors = ToolRegistry(), SensorRegistry()
    indexer = SkillIndexer(skill_locations=[tmp_path / "empty"])
    loader = SkillLoader(indexer)
    skills = PluginSkillRegistry(tools, indexer, loader)

    class SkillPlugin(SamplePlugin):
        def get_skills(self):
            return [("demo", skill_dir)]

    reg = PluginContributionRegistrar(
        tool_registry=tools,
        sensor_registry=sensors,
        operation_registrar=PluginOperationRegistry(tools, get_connection=lambda _: None),
        skill_registrar=skills,
    )
    package, plugin = configured(tmp_path, kinds=("tool", "skill"), plugin=SkillPlugin())
    package.plugin_dir = str(tmp_path)
    register(reg, package, plugin)
    assert tools.is_skill("a-one:demo")
    assert loader.load_skill("a-one:demo") is not None
    reg.unregister("a-one")
    assert not tools.is_skill("a-one:demo")
    assert loader.load_skill("a-one:demo") is None


def test_source_lookup_requires_connection_when_ambiguous():
    sensors = SensorRegistry()
    for connection_id in ("one", "two"):
        sensor_id = f"{connection_id}:source"
        sensors.register(
            "a",
            sensor_id,
            object(),
            SensorSpec(
                sensor_id,
                "Source",
                metadata={
                    "source_type": "stable-source",
                    "connection_id": connection_id,
                },
            ),
        )
    with pytest.raises(ValueError, match="unambiguous connection"):
        sensors.resolve_source_sensor("stable-source")
    assert sensors.resolve_source_sensor("stable-source", connection_id="two")[1] == "two:source"
    assert {item.connection_id for item in sensors.snapshot_user_content_clear_targets()} == {
        "one",
        "two",
    }


@pytest.mark.asyncio
async def test_worker_reload_drains_on_original_runtime_loop(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    loops = []
    runtime_loop = asyncio.get_running_loop()

    class Slow(SamplePlugin):
        async def shutdown(self):
            loops.append(asyncio.get_running_loop())
            entered.set()
            await release.wait()

    manager, connection, _, instances = make_manager(tmp_path, monkeypatch, Slow)
    manager.load_connection(connection.connection_id)
    replacement = asyncio.create_task(asyncio.to_thread(manager.reload_plugin, "a"))
    await asyncio.wait_for(entered.wait(), 2)
    assert len(instances) == 1
    release.set()
    await asyncio.wait_for(replacement, 2)
    assert len(instances) == 2
    assert loops == [runtime_loop]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_cancelled_drain_retains_shutdown_and_blocks_load(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(SamplePlugin):
        async def shutdown(self):
            entered.set()
            await release.wait()

    manager, connection, _, _ = make_manager(tmp_path, monkeypatch, Slow)
    manager.load_connection(connection.connection_id)
    manager.unload_connection(connection.connection_id)
    draining = asyncio.create_task(manager.drain_shutdowns())
    await asyncio.wait_for(entered.wait(), 2)
    draining.cancel()
    with pytest.raises(asyncio.CancelledError):
        await draining
    with pytest.raises(RuntimeError, match="shutdown is pending"):
        manager.load_connection(connection.connection_id)
    release.set()
    await manager.drain_shutdowns()
    manager.load_connection(connection.connection_id)
    await manager.shutdown()


def test_old_package_enable_path_cannot_create_connection(tmp_path, monkeypatch):
    manager, existing, _, _ = make_manager(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="explicit plugin connection"):
        manager.enable_plugin("a")
    assert len(manager.connection_store.list()) == 1


@pytest.mark.asyncio
async def test_package_swap_waits_for_shutdown_before_touching_files(tmp_path, monkeypatch):
    from magi.plugins.installation import PluginInstallationMixin

    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(SamplePlugin):
        async def shutdown(self):
            entered.set()
            await release.wait()

    manager, connection, _, instances = make_manager(tmp_path, monkeypatch, Slow)
    manager.load_connection(connection.connection_id)
    swaps = []

    def swap(self, plan, **kwargs):
        assert release.is_set()
        assert self.get_connection_plugin(connection.connection_id) is None
        swaps.append(plan.plugin_id)
        return (SimpleNamespace(plugin_id=plan.plugin_id), None)

    monkeypatch.setattr(PluginInstallationMixin, "_commit_staged_plugin_package", swap)
    swapping = asyncio.create_task(
        asyncio.to_thread(manager._commit_staged_plugin_package, SimpleNamespace(plugin_id="a"))
    )
    await asyncio.wait_for(entered.wait(), 2)
    assert swaps == []
    release.set()
    await asyncio.wait_for(swapping, 2)
    assert swaps == ["a"]
    assert len(instances) == 2
    await manager.shutdown()


@pytest.mark.asyncio
async def test_clear_and_disconnect_callbacks_are_drained_and_connection_scoped(
    tmp_path, monkeypatch
):
    events = []

    class Recording(SamplePlugin):
        async def shutdown(self):
            events.append(("shutdown", id(self)))

    manager, connection, _, instances = make_manager(tmp_path, monkeypatch, Recording)
    original = manager.load_connection(connection.connection_id)

    async def clear(bound_connection, instance, context):
        assert bound_connection.connection_id == connection.connection_id
        assert context.connection == bound_connection
        assert manager.get_connection_plugin(connection.connection_id) is None
        assert ("shutdown", id(original)) in events
        assert instance is not original
        events.append(("clear", id(instance)))

    manager._content_clearer = clear
    updated = await asyncio.to_thread(
        manager.clear_connection_content, connection.connection_id, expected_revision=0
    )
    assert updated.revision == 1
    assert len(instances) == 3
    assert ("clear", id(instances[1])) in events
    assert ("shutdown", id(instances[1])) in events

    async def disconnect(bound_connection):
        assert bound_connection.connection_id == connection.connection_id
        events.append(("disconnect", bound_connection.connection_id))

    manager._connection_disconnector = disconnect
    await asyncio.to_thread(
        manager.disconnect_connection, connection.connection_id, expected_revision=1
    )
    assert manager.connection_store.list() == []
    assert manager.iter_loaded_plugins() == []
    assert events[-2] == ("disconnect", connection.connection_id)
    assert events[-1] == ("shutdown", id(instances[2]))


def test_uninstall_requires_explicit_connection_disconnect(tmp_path, monkeypatch):
    manager, _, _, _ = make_manager(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Disconnect plugin connections"):
        manager.uninstall_plugin("a")
