from __future__ import annotations

from pathlib import Path
import sys

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import Plugin
from magi.plugins import dependency_installation as dependency_installation_module
from magi.plugins import package_files as package_files_module
from magi.plugins.dependency_installation import (
    PLUGIN_DEPENDENCY_PYTHON_ENV,
    _build_dependency_install_command,
    _filter_installable_dependencies,
    _run_dependency_install_with_progress,
)
from magi.plugins.installation import _resolve_plugin_destination
from magi.plugins.package_files import replace_plugin_directory
from magi.plugins.manager import PluginManager, build_plugin_runtime
from magi.plugins.projections import PluginProjectionService
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry, tool_registry as shared_tool_registry
from magi_plugin_sdk import (
    ExtractionProfileSpec,
    PluginManifest,
    PluginPackageState,
    TemporalSummarySourceFeatures,
)


def _apply_updates(config: AppConfig, updates: dict[str, object]) -> None:
    for path, value in updates.items():
        current = config
        parts = path.split(".")
        for part in parts[:-1]:
            if hasattr(current, part):
                current = getattr(current, part)
                continue
            if isinstance(current, dict):
                current = current.setdefault(part, {})
                continue
            raise KeyError(part)
        last = parts[-1]
        if isinstance(current, dict):
            current[last] = value
        else:
            setattr(current, last, value)


def _patch_plugin_config(
    monkeypatch: pytest.MonkeyPatch,
    config: AppConfig,
) -> None:
    def apply(updates: dict[str, object]) -> bool:
        _apply_updates(config, updates)
        return True

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", apply)
    monkeypatch.setattr("magi.plugins.installation.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.installation.save_config", apply)


def _write_external_tool_plugin(base: Path) -> None:
    plugin_dir = base / "external-tool"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.toml").write_text(
        """
[plugin]
id = "external-tool"
name = "External Tool"
version = "1.0.0"
description = "External test plugin"
author = "Test"
entry_module = "plugin"
entry_class = "ExternalToolPlugin"
official = false
contribution_types = ["tool"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """from magi_plugin_sdk import Plugin
from magi_plugin_sdk.tools import Tool, ToolSchema, ToolExecutionContext, ToolResult

class ExternalHelloTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="external-hello",
            description="Say hello",
            category="test",
        )

    async def execute(self, parameters, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(success=True, data={"message": "hello"})

class ExternalToolPlugin(Plugin):
    def get_tools(self):
        return [ExternalHelloTool]
""".strip(),
        encoding="utf-8",
    )


def _write_reload_test_plugin(base: Path, *, imported_name: str, imported_value: int) -> None:
    plugin_dir = base / "reload-test"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        """
[plugin]
id = "reload-test"
name = "Reload Test"
version = "1.0.0"
description = "Reload behavior test plugin"
author = "Test"
entry_module = "plugin"
entry_class = "ReloadTestPlugin"
official = false
contribution_types = ["tool"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "reader.py").write_text(f"{imported_name} = {imported_value}\n", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        f"""from magi_plugin_sdk import Plugin
from .reader import {imported_name}

class ReloadTestPlugin(Plugin):
    def __init__(self):
        self.marker = {imported_name}

    def get_tools(self):
        return []
""".strip(),
        encoding="utf-8",
    )


def _write_install_test_plugin(
    base: Path,
    *,
    plugin_id: str,
    version: str,
    marker: str,
    dependencies: list[str] | None = None,
    fail_on_import: bool = False,
) -> Path:
    plugin_dir = base / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    dependencies_line = ""
    if dependencies:
        quoted = ", ".join(f'"{item}"' for item in dependencies)
        dependencies_line = f"\ndependencies = [{quoted}]"
    (plugin_dir / "plugin.toml").write_text(
        f"""
[plugin]
id = "{plugin_id}"
name = "Install Test"
version = "{version}"
description = "Install behavior test plugin"
author = "Test"
entry_module = "plugin"
entry_class = "InstallTestPlugin"
official = false
contribution_types = ["tool"]{dependencies_line}
""".strip(),
        encoding="utf-8",
    )
    plugin_source = (
        'raise RuntimeError("new plugin failed to load")'
        if fail_on_import
        else f"""from magi_plugin_sdk import Plugin

class InstallTestPlugin(Plugin):
    marker = \"{marker}\"

    def get_tools(self):
        return []
""".strip()
    )
    (plugin_dir / "plugin.py").write_text(plugin_source, encoding="utf-8")
    return plugin_dir


@pytest.mark.asyncio
async def test_plugin_manager_discovers_external_plugins_and_loads_enabled_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_external_tool_plugin(tmp_path)
    config = AppConfig()
    config.plugins.packages["external-tool"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        settings={},
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    discovered = manager.scan(persist_discovery=True)
    assert [item.manifest.plugin_id for item in discovered] == ["external-tool"]

    manager.activate_enabled_plugins()
    assert "external-hello" in tool_registry.list_tools()

    manager.disable_plugin("external-tool")
    assert "external-hello" not in tool_registry.list_tools()


def test_plugin_manager_persists_newly_discovered_plugins_as_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_external_tool_plugin(tmp_path)
    config = AppConfig()
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    packages = manager.scan(persist_discovery=True)
    assert packages[0].enabled is False
    package_settings = config.plugins.packages["external-tool"]
    if isinstance(package_settings, dict):
        assert package_settings["enabled"] is False
        assert package_settings["trusted"] is False
    else:
        assert package_settings.enabled is False
        assert package_settings.trusted is False


def test_core_tools_plugin_registers_memory_query_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    config.plugins.packages["core-tools"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="builtin",
        settings={},
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )

    builtin_plugins_root = Path(__file__).resolve().parents[3] / "plugins"
    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[builtin_plugins_root],
    )

    packages = manager.scan(persist_discovery=False)
    assert any(item.manifest.plugin_id == "core-tools" for item in packages)

    manager.activate_enabled_plugins()

    assert "memory_query" in tool_registry.list_tools()


def _write_shutdown_test_plugin(base: Path) -> None:
    """Plugin whose shutdown() flips a class-level flag so we can observe it."""
    plugin_dir = base / "shutdown-test"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        """
[plugin]
id = "shutdown-test"
name = "Shutdown Test"
version = "1.0.0"
description = "Plugin shutdown hook test"
author = "Test"
entry_module = "plugin"
entry_class = "ShutdownTestPlugin"
official = false
contribution_types = ["tool"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """from magi_plugin_sdk import Plugin

class ShutdownTestPlugin(Plugin):
    shutdown_calls: list[int] = []

    async def shutdown(self) -> None:
        # Bump a class-level counter so the test can verify the host
        # called us — instance vs class is mocked here because every load
        # creates a fresh instance.
        ShutdownTestPlugin.shutdown_calls.append(1)
""".strip(),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_unload_plugin_invokes_shutdown_hook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression: previously unload_plugin dropped the plugin from the
    registry without ever giving it a chance to clean up sensors /
    subprocesses / timers. Every reload (settings update, disable) leaked
    the old instance. Now the host must invoke `plugin.shutdown()`."""
    _write_shutdown_test_plugin(tmp_path)
    config = AppConfig()
    config.plugins.packages["shutdown-test"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        settings={},
    )

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config",
        lambda updates: _apply_updates(config, updates) or True,
    )

    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    manager.scan(persist_discovery=True)
    manager.activate_enabled_plugins()

    # Plugin loader uses entry_module="plugin", flattens into a single
    # module under magi_plugin_<id>. Read the class through the loaded
    # instance to avoid coupling to the loader's exact module name.
    instance = manager._plugin_instances["shutdown-test"]
    plugin_cls = type(instance)
    assert plugin_cls.shutdown_calls == []

    manager.unload_plugin("shutdown-test")

    # Drain pending shutdown tasks. unload_plugin schedules shutdown on
    # the running loop and returns immediately; we yield so the task can
    # run before we assert.
    import asyncio

    # Give the loop one cycle. With asyncio mode=auto, pytest-asyncio is
    # already in an event loop here.
    for _ in range(50):
        if plugin_cls.shutdown_calls:
            break
        await asyncio.sleep(0.01)

    assert plugin_cls.shutdown_calls == [1], "Host did not invoke plugin.shutdown() on unload"


def test_plugin_manager_reload_clears_cached_plugin_submodules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_reload_test_plugin(tmp_path, imported_name="VALUE", imported_value=1)
    config = AppConfig()
    config.plugins.packages["reload-test"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        settings={},
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    manager.scan(persist_discovery=True)
    manager.activate_enabled_plugins()

    assert manager._plugin_instances["reload-test"].marker == 1
    assert "magi_plugin_reload_test.reader" in sys.modules

    _write_reload_test_plugin(tmp_path, imported_name="DETECT_STEAM_ROOT", imported_value=2)
    manager.reload_plugin("reload-test")

    assert manager._plugin_instances["reload-test"].marker == 2
    reader_module = sys.modules["magi_plugin_reload_test.reader"]
    assert getattr(reader_module, "DETECT_STEAM_ROOT") == 2
    assert not hasattr(reader_module, "VALUE")


def test_install_plugin_from_directory_keeps_existing_plugin_until_staging_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    source_root = tmp_path / "incoming"
    existing_dir = _write_install_test_plugin(
        user_root,
        plugin_id="swap-test",
        version="1.0.0",
        marker="old-version",
    )
    incoming_dir = _write_install_test_plugin(
        source_root,
        plugin_id="swap-test",
        version="2.0.0",
        marker="new-version",
        dependencies=["broken-dependency"],
    )

    config = AppConfig()
    tool_registry = ToolRegistry()

    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager.scan(persist_discovery=True)

    unload_calls: list[str] = []
    original_unload = manager.unload_plugin

    def tracking_unload(plugin_id: str) -> None:
        unload_calls.append(plugin_id)
        original_unload(plugin_id)

    monkeypatch.setattr(manager, "unload_plugin", tracking_unload)

    def fail_install_dependencies(dependencies: list[str], plugin_dir: Path) -> None:
        _ = dependencies, plugin_dir
        raise RuntimeError("dependency install failed")

    monkeypatch.setattr(
        PluginManager, "_install_dependencies", staticmethod(fail_install_dependencies)
    )

    with pytest.raises(RuntimeError, match="dependency install failed"):
        manager.install_plugin_from_directory(incoming_dir)

    assert unload_calls == []
    assert existing_dir.exists()
    assert "old-version" in (existing_dir / "plugin.py").read_text(encoding="utf-8")
    assert "new-version" not in (existing_dir / "plugin.py").read_text(encoding="utf-8")
    assert not list(user_root.glob(".swap-test-*"))
    assert not list(tmp_path.glob(".user-plugins-swap-test-*"))


def test_install_plugin_from_directory_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    source_root = tmp_path / "incoming"
    incoming_dir = _write_install_test_plugin(
        source_root,
        plugin_id="progress-test",
        version="1.0.0",
        marker="installed",
    )

    config = AppConfig()
    tool_registry = ToolRegistry()

    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    progress_events: list[tuple[str, str, float | None]] = []

    state = manager.install_plugin_from_directory(
        incoming_dir,
        progress_reporter=lambda stage, message, progress: progress_events.append(
            (stage, message, progress)
        ),
    )

    assert state.manifest.plugin_id == "progress-test"
    assert state.enabled is True
    assert [event[0] for event in progress_events] == [
        "validate",
        "stage",
        "scan",
        "activate",
        "completed",
    ]
    assert progress_events[-1][2] == 100.0


def test_new_plugin_load_failure_leaves_no_installed_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    incoming_dir = _write_install_test_plugin(
        tmp_path / "incoming",
        plugin_id="new-rollback-test",
        version="1.0.0",
        marker="broken",
        fail_on_import=True,
    )
    config = AppConfig()
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )

    with pytest.raises(RuntimeError, match="new plugin failed to load"):
        manager.install_plugin_from_directory(incoming_dir)

    assert not (user_root / "new-rollback-test").exists()
    assert "new-rollback-test" not in config.plugins.packages
    assert manager.get_package("new-rollback-test") is None
    assert manager.get_loaded_plugin("new-rollback-test") is None
    assert not list(user_root.glob(".new-rollback-test-*"))
    assert not list(tmp_path.glob(".user-plugins-new-rollback-test-*"))


def test_plugin_update_load_failure_restores_previous_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    existing_dir = _write_install_test_plugin(
        user_root,
        plugin_id="update-rollback-test",
        version="1.0.0",
        marker="old-version",
    )
    incoming_dir = _write_install_test_plugin(
        tmp_path / "incoming",
        plugin_id="update-rollback-test",
        version="2.0.0",
        marker="broken-version",
        fail_on_import=True,
    )
    config = AppConfig()
    config.plugins.packages["update-rollback-test"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        manifest_path=str(existing_dir / "plugin.toml"),
        official=False,
        settings={"preserved": "value"},
    )
    original_config = config.plugins.packages["update-rollback-test"].model_dump(mode="json")
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager.scan(persist_discovery=False)
    manager.activate_enabled_plugins()
    assert manager.get_loaded_plugin("update-rollback-test").marker == "old-version"

    with pytest.raises(RuntimeError, match="new plugin failed to load"):
        manager.install_plugin_from_directory(incoming_dir)

    assert "old-version" in (existing_dir / "plugin.py").read_text(encoding="utf-8")
    assert "broken-version" not in (existing_dir / "plugin.py").read_text(encoding="utf-8")
    assert (
        config.plugins.packages["update-rollback-test"].model_dump(mode="json") == original_config
    )
    restored_state = manager.get_package("update-rollback-test")
    assert restored_state is not None
    assert restored_state.enabled is True
    assert restored_state.trusted is True
    assert restored_state.loaded is True
    assert restored_state.healthy is True
    assert restored_state.last_error is None
    assert manager.get_loaded_plugin("update-rollback-test").marker == "old-version"
    assert not list(user_root.glob(".update-rollback-test-*"))
    assert not list(tmp_path.glob(".user-plugins-update-rollback-test-*"))


def test_plugin_install_destination_must_remain_inside_user_root(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    outside_root = tmp_path / "outside"
    user_root.mkdir()
    outside_root.mkdir()
    (user_root / "linked-plugin").symlink_to(outside_root, target_is_directory=True)

    assert (
        _resolve_plugin_destination(user_root, "safe-plugin")
        == (user_root / "safe-plugin").resolve()
    )
    with pytest.raises(ValueError, match="must remain inside"):
        _resolve_plugin_destination(user_root, "../outside")
    with pytest.raises(ValueError, match="must remain inside"):
        _resolve_plugin_destination(user_root, "linked-plugin")


def test_install_plugin_from_directory_still_rejects_builtin_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    incoming_dir = _write_install_test_plugin(
        tmp_path / "incoming",
        plugin_id="core-tools",
        version="2.0.0",
        marker="replacement",
    )
    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        request_sensor_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager._package_states["core-tools"] = PluginPackageState(
        manifest=PluginManifest(
            id="core-tools",
            name="Core Tools",
            version="1.0.0",
            source="builtin",
        )
    )
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    with pytest.raises(ValueError, match="Cannot overwrite builtin plugin"):
        manager.install_plugin_from_directory(incoming_dir)

    assert not (user_root / "core-tools").exists()


def test_dependency_install_runner_reports_subprocess_output() -> None:
    progress_events: list[tuple[str, str, float | None]] = []

    result = _run_dependency_install_with_progress(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.write('collecting\\n'); sys.stdout.flush(); "
                "sys.stderr.write('installing\\n'); sys.stderr.flush()"
            ),
        ],
        lambda stage, message, progress: progress_events.append((stage, message, progress)),
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["collecting", "installing"]
    assert progress_events == [
        ("dependencies", "collecting", None),
        ("dependencies", "installing", None),
    ]


def test_dependency_install_command_uses_configured_python_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current_python = sys.executable
    monkeypatch.setenv(PLUGIN_DEPENDENCY_PYTHON_ENV, current_python)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys,
        "executable",
        "/Applications/Magi.app/Contents/Resources/sidecar-dist/magi-backend",
    )

    lock = tmp_path / "requirements.lock"
    lock.write_text(f"example-package==1.0.0 --hash=sha256:{'a' * 64}\n", encoding="utf-8")
    cmd = _build_dependency_install_command(lock, tmp_path / ".deps", quiet=False)

    assert cmd[:4] == [current_python, "-m", "pip", "install"]


def test_dependency_install_command_rejects_frozen_sidecar_without_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(PLUGIN_DEPENDENCY_PYTHON_ENV, raising=False)
    monkeypatch.delenv("MAGI_BACKEND_PYTHON", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys,
        "executable",
        "/Applications/Magi.app/Contents/Resources/sidecar-dist/magi-backend",
    )
    monkeypatch.setattr(dependency_installation_module.shutil, "which", lambda _name: None)

    lock = tmp_path / "requirements.lock"
    lock.write_text(f"example-package==1.0.0 --hash=sha256:{'a' * 64}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=PLUGIN_DEPENDENCY_PYTHON_ENV):
        _build_dependency_install_command(lock, tmp_path / ".deps", quiet=False)


def test_replace_plugin_directory_rolls_back_when_promotion_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "marker.txt").write_text("new", encoding="utf-8")

    dest_dir = tmp_path / "installed"
    dest_dir.mkdir()
    (dest_dir / "marker.txt").write_text("old", encoding="utf-8")

    original_replace = Path.replace
    replace_calls: list[tuple[str, str]] = []

    def flaky_replace(self: Path, target: Path) -> Path:
        replace_calls.append((str(self), str(target)))
        if len(replace_calls) == 2:
            raise OSError("promotion failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    with pytest.raises(OSError, match="promotion failed"):
        replace_plugin_directory(source_dir, dest_dir)

    assert (dest_dir / "marker.txt").read_text(encoding="utf-8") == "old"
    assert len(replace_calls) >= 2


def test_filter_installable_dependencies_respects_environment_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = dependency_installation_module.default_environment()
    environment["sys_platform"] = "darwin"
    monkeypatch.setattr(dependency_installation_module, "default_environment", lambda: environment)

    installable, skipped = _filter_installable_dependencies(
        [
            "requests>=2",
            "winrt-runtime>=2.0; sys_platform == 'win32'",
            "not a valid requirement @@@",
        ]
    )

    assert installable == ["requests>=2", "not a valid requirement @@@"]
    assert skipped == ["winrt-runtime>=2.0; sys_platform == 'win32'"]


def test_build_plugin_runtime_threads_injected_tool_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_external_tool_plugin(tmp_path)
    config = AppConfig()
    config.plugins.packages["external-tool"] = PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        settings={},
    )

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )
    monkeypatch.setattr("magi.plugins.manager._resolve_search_paths", lambda: [tmp_path])

    try:
        build_plugin_runtime(
            tool_registry=shared_tool_registry,
            request_sensor_schedule_refresh=lambda: None,
            sensor_registry=SensorRegistry(),
        )

        assert "external-hello" in shared_tool_registry.list_tools()
    finally:
        shared_tool_registry.unregister("external-hello")


def test_plugin_projection_service_collects_temporal_summary_features_from_loaded_plugins() -> None:
    class ChromeFeaturePlugin(Plugin):
        def build_temporal_summary_features(self, *, source_type, events, summary_category, period_start, period_end):  # type: ignore[no-untyped-def]
            _ = summary_category, period_start, period_end
            assert source_type == "chrome_history"
            assert len(events) == 3
            return {
                "feature_type": "chrome_history",
                "event_count": 3,
                "visit_count": 4,
                "unique_domain_count": 2,
                "focus_domain": "openai.com",
                "focus_share": 2 / 3,
                "session_count": 1,
                "top_domains": [
                    {"domain": "openai.com", "count": 2},
                    {"domain": "github.com", "count": 1},
                ],
                "revisit_domains": ["openai.com"],
                "summary_lines": [
                    "Browsing concentrated heavily on openai.com.",
                    "Repeated visits clustered around openai.com.",
                    "Browsing stayed within a small set of sites.",
                ],
            }

    service = PluginProjectionService(iter_loaded_plugins=lambda: [ChromeFeaturePlugin()])

    features = service.build_temporal_summary_features(
        events=[
            {
                "event_id": "evt-1",
                "source": "chrome_history",
                "content": "OpenAI docs",
                "metadata_json": {
                    "activity_snapshot": {
                        "provenance": {
                            "domain": "openai.com",
                            "merged_visit_count": 2,
                        }
                    }
                },
            },
            {
                "event_id": "evt-2",
                "source": "chrome_history",
                "content": "GitHub issues",
                "metadata_json": {
                    "activity_snapshot": {
                        "provenance": {
                            "domain": "github.com",
                            "merged_visit_count": 1,
                        }
                    }
                },
            },
            {
                "event_id": "evt-3",
                "source": "chrome_history",
                "content": "OpenAI pricing",
                "metadata_json": {
                    "activity_snapshot": {
                        "provenance": {
                            "domain": "openai.com",
                            "merged_visit_count": 1,
                        }
                    }
                },
            },
        ],
        summary_category="day",
        period_start=1710000000.0,
        period_end=1710003600.0,
    )

    assert features == {
        "chrome_history": {
            "feature_type": "chrome_history",
            "event_count": 3,
            "visit_count": 4,
            "unique_domain_count": 2,
            "focus_domain": "openai.com",
            "focus_share": pytest.approx(2 / 3, rel=1e-3),
            "session_count": 1,
            "top_domains": [
                {"domain": "openai.com", "count": 2},
                {"domain": "github.com", "count": 1},
            ],
            "revisit_domains": ["openai.com"],
            "summary_lines": [
                "Browsing concentrated heavily on openai.com.",
                "Repeated visits clustered around openai.com.",
                "Browsing stayed within a small set of sites.",
            ],
        }
    }


def test_plugin_projection_service_collects_extraction_profiles_from_loaded_plugins() -> None:
    class SourceProfilePlugin(Plugin):
        def get_extraction_profiles(self):  # type: ignore[no-untyped-def]
            return [
                ExtractionProfileSpec(
                    profile_id="source.example",
                    source_types=["example"],
                    allowed_entity_types=["software"],
                    allowed_predicates=["USES"],
                    allow_assertion=False,
                )
            ]

    service = PluginProjectionService(iter_loaded_plugins=lambda: [SourceProfilePlugin()])

    profiles = service.iter_extraction_profiles()

    assert len(profiles) == 1
    assert profiles[0].profile_id == "source.example"
    assert profiles[0].source_types == ["example"]


def test_plugin_projection_service_passes_temporal_feature_budget_to_new_hooks() -> None:
    class BudgetAwarePlugin(Plugin):
        def build_temporal_summary_features(self, *, source_type, events, summary_category, period_start, period_end, budget=None):  # type: ignore[no-untyped-def]
            _ = summary_category, period_start, period_end
            assert source_type == "music"
            assert len(events) == 1
            assert budget is not None
            return TemporalSummarySourceFeatures(
                source_type=source_type,
                total_event_count=budget.total_event_count,
                covered_event_count=budget.available_event_count,
                omitted_event_count=budget.omitted_event_count,
                summary_lines=["Music listening was compacted for L3."],
            )

    service = PluginProjectionService(iter_loaded_plugins=lambda: [BudgetAwarePlugin()])

    features = service.build_temporal_summary_features(
        events=[{"event_id": "evt-1", "source": "music", "content": "song"}],
        summary_category="day",
        period_start=1.0,
        period_end=2.0,
        feature_budgets={
            "music": {
                "source_type": "music",
                "total_event_count": 10,
                "available_event_count": 4,
                "selected_event_count": 1,
                "omitted_event_count": 6,
            }
        },
    )

    assert features["music"]["total_event_count"] == 10
    assert features["music"]["covered_event_count"] == 4
    assert features["music"]["omitted_event_count"] == 6
