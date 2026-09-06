from __future__ import annotations

from pathlib import Path
import sys
import asyncio
import threading

import pytest

from magi.utils.runtime import RuntimePaths
from runtime_fixtures import instantiate_fixture_plugin, bind_fixture_plugin

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
from magi.plugins.discovery import load_plugin_manifest
from magi.plugins.package_files import replace_plugin_directory
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_installed_source_sha256,
    compute_package_sha256,
    purge_plugin_bytecode_caches,
)
from magi.plugins.manager import PluginManager, build_plugin_runtime
from magi.plugins.projections import PluginProjectionService
from magi.plugins.sources import SourceRegistry
from magi.tools.registry import ToolRegistry, tool_registry as shared_tool_registry
from magi_plugin_sdk import (
    ExtractionProfileSpec,
    PluginManifest,
    PluginPackageState,
    TemporalSummarySourceFeatures,
)


@pytest.fixture(autouse=True)
def isolated_connection_store(monkeypatch, tmp_path):
    paths = RuntimePaths(base_dir=tmp_path / "runtime")
    monkeypatch.setattr("magi.plugins.connections.get_runtime_paths", lambda: paths)


def _connect(manager, plugin_id, *, enabled=True):
    return manager.create_connection(plugin_id, display_name="Test account", enabled=enabled)


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
    monkeypatch.setattr(
        "magi.plugins.installation.delete_plugin_package",
        lambda plugin_id: config.plugins.packages.pop(plugin_id, None) is not None,
    )


def _configure_registry_update(
    config: AppConfig,
    *,
    installed_manifest: PluginManifest,
    incoming_dir: Path,
) -> dict[str, object]:
    plugin_id = installed_manifest.plugin_id
    registry_url = "https://example.test/registry.json"
    repo_url = "https://github.com/example/plugins.git"
    configured = config.plugins.packages.get(
        plugin_id,
        PluginSettings(
            trusted=True,
            source="external",
            manifest_path=installed_manifest.manifest_path,
        ),
    )
    if isinstance(configured, dict):
        configured = PluginSettings.model_validate(configured)
    installed_dir = Path(installed_manifest.plugin_dir)
    purge_plugin_bytecode_caches(installed_dir)
    config.plugins.packages[plugin_id] = configured.model_copy(
        update={
            "enabled": True,
            "trusted": True,
            "source": "external",
            "manifest_path": installed_manifest.manifest_path,
            "install_origin": "registry",
            "registry_source": registry_url,
            "registry_repo_url": repo_url,
            "package_sha256": compute_installed_source_sha256(installed_dir),
            "installed_package_sha256": compute_installed_package_sha256(
                installed_dir
            ),
        }
    )
    return {
        "install_origin": "registry",
        "registry_source": registry_url,
        "registry_repo_url": repo_url,
        "package_sha256": compute_package_sha256(incoming_dir),
        "expected_registry_update_source": (registry_url, repo_url),
    }


def _write_external_tool_plugin(base: Path) -> None:
    plugin_dir = base / "external-tool"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.toml").write_text(
        """
[plugin]
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
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
            effect_class="read_only",
            effect_replay_policy="read_only",
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
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
id = "reload-test"
name = "Reload Test"
version = "1.0.0"
description = "Reload behavior test plugin"
author = "Test"
entry_module = "plugin"
entry_class = "ReloadTestPlugin"
official = false
contribution_types = []
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
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
id = "{plugin_id}"
name = "Install Test"
version = "{version}"
description = "Install behavior test plugin"
author = "Test"
entry_module = "plugin"
entry_class = "InstallTestPlugin"
official = false
contribution_types = []{dependencies_line}
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


def _write_install_test_library(
    base: Path,
    *,
    plugin_id: str,
    version: str,
    marker: str,
) -> Path:
    plugin_dir = base / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        f"""
[plugin]
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
id = "{plugin_id}"
name = "Install Test Library"
version = "{version}"
description = "Install dependency race test library"
author = "Test"
official = false
kind = "library"
contribution_types = []
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        f'MARKER = "{marker}"\n',
        encoding="utf-8",
    )
    return plugin_dir


def _write_install_test_consumer(
    base: Path,
    *,
    plugin_id: str,
    library_id: str,
) -> Path:
    plugin_dir = base / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        f"""
[plugin]
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
id = "{plugin_id}"
name = "Install Test Consumer"
version = "1.0.0"
description = "Install dependency race test consumer"
author = "Test"
entry_module = "plugin"
entry_class = "InstallTestConsumer"
official = false
contribution_types = []
depends_on = ["{library_id}"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """from magi_plugin_sdk import Plugin


class InstallTestConsumer(Plugin):
    pass
""".strip(),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.mark.asyncio
async def test_plugin_manager_discovers_external_plugins_and_loads_enabled_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_external_tool_plugin(tmp_path)
    config = AppConfig()
    config.plugins.packages["external-tool"] = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=str(tmp_path / "external-tool" / "plugin.toml"),
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )

    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=tool_registry,
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    discovered = manager.scan(persist_discovery=True)
    assert [item.manifest.plugin_id for item in discovered] == ["external-tool"]

    connection = _connect(manager, "external-tool")
    manager.activate_enabled_plugins()
    assert f"{connection.connection_id}:external-hello" in tool_registry.list_tools()

    await asyncio.to_thread(manager.update_connection, connection.connection_id, expected_revision=0, enabled=False)
    assert f"{connection.connection_id}:external-hello" not in tool_registry.list_tools()


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
        instance_factory=instantiate_fixture_plugin,
        tool_registry=tool_registry,
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    packages = manager.scan(persist_discovery=True)
    assert packages[0].enabled is False
    package_settings = config.plugins.packages["external-tool"]
    if isinstance(package_settings, dict):
        assert "enabled" not in package_settings
        assert package_settings["trusted"] is False
    else:
        assert "enabled" not in package_settings.model_dump()
        assert package_settings.trusted is False


def test_core_tools_plugin_registers_memory_query_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    config.plugins.packages["core-tools"] = PluginSettings(
        trusted=True,
        source="builtin",
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )

    builtin_plugins_root = Path(__file__).resolve().parents[3] / "plugins"
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=tool_registry,
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
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
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
id = "shutdown-test"
name = "Shutdown Test"
version = "1.0.0"
description = "Plugin shutdown hook test"
author = "Test"
entry_module = "plugin"
entry_class = "ShutdownTestPlugin"
official = false
contribution_types = []
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
    registry without ever giving it a chance to clean up sources /
    subprocesses / timers. Every reload (settings update, disable) leaked
    the old instance. Now the host must invoke `plugin.shutdown()`."""
    _write_shutdown_test_plugin(tmp_path)
    config = AppConfig()
    config.plugins.packages["shutdown-test"] = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=str(tmp_path / "shutdown-test" / "plugin.toml"),
    )

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config",
        lambda updates: _apply_updates(config, updates) or True,
    )

    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    manager.scan(persist_discovery=True)
    connection = _connect(manager, "shutdown-test")
    manager.activate_enabled_plugins()

    # Plugin loader uses entry_module="plugin", flattens into a single
    # module under magi_plugin_<id>. Read the class through the loaded
    # instance to avoid coupling to the loader's exact module name.
    instance = manager.get_connection_plugin(connection.connection_id)
    plugin_cls = type(instance)
    assert plugin_cls.shutdown_calls == []

    await manager.unload_plugin_async("shutdown-test")

    assert plugin_cls.shutdown_calls == [1], "Host did not invoke plugin.shutdown() on unload"


def test_plugin_manager_reload_clears_cached_plugin_submodules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_reload_test_plugin(tmp_path, imported_name="VALUE", imported_value=1)
    config = AppConfig()
    config.plugins.packages["reload-test"] = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=str(tmp_path / "reload-test" / "plugin.toml"),
    )
    tool_registry = ToolRegistry()

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )

    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=tool_registry,
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )

    manager.scan(persist_discovery=True)
    connection = _connect(manager, "reload-test")
    manager.activate_enabled_plugins()

    assert manager.get_connection_plugin(connection.connection_id).marker == 1
    assert "magi_plugin_reload_test.reader" in sys.modules

    _write_reload_test_plugin(tmp_path, imported_name="DETECT_STEAM_ROOT", imported_value=2)
    manager.reload_plugin("reload-test")

    assert manager.get_connection_plugin(connection.connection_id).marker == 2
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
        instance_factory=instantiate_fixture_plugin,
        tool_registry=tool_registry,
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager.scan(persist_discovery=True)
    existing_state = manager.get_package("swap-test")
    assert existing_state is not None
    update_kwargs = _configure_registry_update(
        config,
        installed_manifest=existing_state.manifest,
        incoming_dir=incoming_dir,
    )

    unload_calls: list[str] = []
    original_unload = manager.unload_plugin

    def tracking_unload(plugin_id: str) -> None:
        unload_calls.append(plugin_id)
        original_unload(plugin_id)

    monkeypatch.setattr(manager, "unload_plugin", tracking_unload)

    def fail_install_dependencies(
        dependencies: list[str],
        plugin_dir: Path,
        **_kwargs: object,
    ) -> None:
        _ = dependencies, plugin_dir
        raise RuntimeError("dependency install failed")

    monkeypatch.setattr(
        PluginManager, "_install_dependencies", staticmethod(fail_install_dependencies)
    )

    with pytest.raises(RuntimeError, match="dependency install failed"):
        manager.install_plugin_from_directory(
            incoming_dir,
            **update_kwargs,
        )

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
        instance_factory=instantiate_fixture_plugin,
        tool_registry=tool_registry,
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
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
    assert state.enabled is False
    assert manager.connection_store.list(state.manifest.plugin_id) == []
    assert [event[0] for event in progress_events] == [
        "validate",
        "stage",
        "scan",
        "completed",
    ]
    assert progress_events[-1][2] == 100.0


def test_plugin_lifecycle_prepares_concurrently_but_rejects_stale_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    plugin_id = "serialized-install"
    first_source = _write_install_test_plugin(
        tmp_path / "incoming-first",
        plugin_id=plugin_id,
        version="1.0.0",
        marker="first",
    )
    second_source = _write_install_test_plugin(
        tmp_path / "incoming-second",
        plugin_id=plugin_id,
        version="2.0.0",
        marker="second",
    )
    config = AppConfig()
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.installation.get_config", lambda: config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    config_versions: list[str] = []

    def record_config(updates: dict[str, object]) -> bool:
        digest = updates.get(f"plugins.packages.{plugin_id}.package_sha256")
        if digest:
            version = "1.0.0" if digest == compute_package_sha256(first_source) else "2.0.0"
            config_versions.append(version)
        _apply_updates(config, updates)
        return True

    monkeypatch.setattr("magi.plugins.manager.save_config", record_config)
    monkeypatch.setattr("magi.plugins.installation.save_config", record_config)

    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )

    first_staged = threading.Event()
    release_first = threading.Event()
    second_staged = threading.Event()
    release_second = threading.Event()
    progress_events: list[tuple[str, str]] = []
    progress_lock = threading.Lock()

    def reporter(label: str):
        def report(stage: str, _message: str, _progress: float | None) -> None:
            with progress_lock:
                progress_events.append((label, stage))
            if label == "first" and stage == "stage":
                first_staged.set()
                if not release_first.wait(timeout=5):
                    raise TimeoutError("Timed out waiting to release the first install")
            if label == "second" and stage == "stage":
                second_staged.set()
                if not release_second.wait(timeout=5):
                    raise TimeoutError("Timed out waiting to release the second install")

        return report

    results: dict[str, PluginPackageState] = {}
    errors: list[BaseException] = []

    def install(label: str, source: Path) -> None:
        try:
            results[label] = manager.install_plugin_from_directory(
                source,
                progress_reporter=reporter(label),
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first_thread = threading.Thread(
        target=install,
        args=("first", first_source),
        daemon=True,
    )
    second_thread = threading.Thread(
        target=install,
        args=("second", second_source),
        daemon=True,
    )
    first_thread.start()
    assert first_staged.wait(timeout=5)
    second_thread.start()

    assert second_staged.wait(timeout=0.5)
    release_first.set()
    first_thread.join(timeout=5)
    release_second.set()
    second_thread.join(timeout=5)

    assert first_thread.is_alive() is False
    assert second_thread.is_alive() is False
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert "Cannot replace an installed plugin" in str(errors[0])
    assert ("first", "stage") in progress_events
    assert ("second", "stage") in progress_events
    assert config_versions == ["1.0.0"]
    assert results["first"].manifest.version == "1.0.0"
    assert "second" not in results
    final_state = manager.get_package(plugin_id)
    assert final_state is not None
    assert final_state.manifest.version == "1.0.0"
    assert final_state.enabled is False
    assert final_state.trusted is False
    assert not [plugin for plugin in manager.iter_loaded_plugins() if plugin.plugin_id == plugin_id]
    manager.authorize_package(plugin_id, expected_package_sha256=PluginSettings.model_validate(config.plugins.packages[plugin_id]).package_sha256)
    connection = _connect(manager, plugin_id)
    assert manager.get_connection_plugin(connection.connection_id).marker == "first"
    assert 'version = "1.0.0"' in (user_root / plugin_id / "plugin.toml").read_text(
        encoding="utf-8"
    )


def test_plugin_install_rejects_state_changed_during_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    plugin_id = "state-generation-install"
    initial_source = _write_install_test_plugin(
        tmp_path / "incoming-initial",
        plugin_id=plugin_id,
        version="1.0.0",
        marker="initial",
    )
    update_source = _write_install_test_plugin(
        tmp_path / "incoming-update",
        plugin_id=plugin_id,
        version="2.0.0",
        marker="update",
    )
    config = AppConfig()
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.installation.get_config", lambda: config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    def save(updates: dict[str, object]) -> bool:
        _apply_updates(config, updates)
        return True

    monkeypatch.setattr("magi.plugins.manager.save_config", save)
    monkeypatch.setattr("magi.plugins.installation.save_config", save)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager.install_plugin_from_directory(initial_source)
    initial_state = manager.get_package(plugin_id)
    assert initial_state is not None
    update_kwargs = _configure_registry_update(
        config,
        installed_manifest=initial_state.manifest,
        incoming_dir=update_source,
    )
    preparation_started = threading.Event()
    release_preparation = threading.Event()
    errors: list[BaseException] = []

    def reporter(stage: str, _message: str, _progress: float | None) -> None:
        if stage == "stage":
            preparation_started.set()
            if not release_preparation.wait(timeout=5):
                raise TimeoutError("Timed out waiting to release plugin preparation")

    def install_update() -> None:
        try:
            manager.install_plugin_from_directory(
                update_source,
                progress_reporter=reporter,
                **update_kwargs,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    install_thread = threading.Thread(target=install_update, daemon=True)
    install_thread.start()
    assert preparation_started.wait(timeout=5)
    config.plugins.packages[plugin_id].trusted = False
    manager.scan(persist_discovery=False)
    release_preparation.set()
    install_thread.join(timeout=5)

    assert install_thread.is_alive() is False
    assert len(errors) == 1
    assert "target changed" in str(errors[0])
    state = manager.get_package(plugin_id)
    assert state is not None
    assert state.manifest.version == "1.0.0"
    assert state.trusted is False
    assert 'version = "1.0.0"' in (user_root / plugin_id / "plugin.toml").read_text(
        encoding="utf-8"
    )


def test_plugin_install_rejects_dependency_replaced_during_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    library_id = "shared-library"
    consumer_id = "dependency-race-consumer"
    initial_library = _write_install_test_library(
        user_root,
        plugin_id=library_id,
        version="1.0.0",
        marker="initial",
    )
    replacement_library = _write_install_test_library(
        tmp_path / "replacement",
        plugin_id=library_id,
        version="2.0.0",
        marker="replacement",
    )
    incoming_consumer = _write_install_test_consumer(
        tmp_path / "incoming",
        plugin_id=consumer_id,
        library_id=library_id,
    )
    registry_url = "https://example.test/registry.json"
    repo_url = "https://github.com/example/plugins.git"
    config = AppConfig()
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager.scan(persist_discovery=True)
    initial_state = manager.get_package(library_id)
    assert initial_state is not None
    dependency_package_sha256 = compute_installed_source_sha256(initial_library)
    dependency_installed_package_sha256 = compute_installed_package_sha256(
        initial_library
    )
    consumer_package_sha256 = compute_package_sha256(incoming_consumer)
    config.plugins.packages[library_id] = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=str(initial_library / "plugin.toml"),
        install_origin="registry",
        registry_source=registry_url,
        registry_repo_url=repo_url,
        package_sha256=dependency_package_sha256,
        installed_package_sha256=dependency_installed_package_sha256,
    )
    manager.scan(persist_discovery=False)

    preparation_started = threading.Event()
    release_preparation = threading.Event()
    errors: list[BaseException] = []

    def reporter(stage: str, _message: str, _progress: float | None) -> None:
        if stage == "stage":
            preparation_started.set()
            if not release_preparation.wait(timeout=5):
                raise TimeoutError("Timed out waiting to release plugin preparation")

    def install_consumer() -> None:
        try:
            manager.install_plugin_from_directory(
                incoming_consumer,
                progress_reporter=reporter,
                install_origin="registry",
                registry_source=registry_url,
                registry_repo_url=repo_url,
                package_sha256=consumer_package_sha256,
                dependency_package_sha256={
                    library_id: dependency_package_sha256,
                },
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    install_thread = threading.Thread(target=install_consumer, daemon=True)
    install_thread.start()
    assert preparation_started.wait(timeout=5)

    manager.uninstall_plugin(library_id)
    manager.install_plugin_from_directory(replacement_library)
    release_preparation.set()
    install_thread.join(timeout=5)

    assert install_thread.is_alive() is False
    assert len(errors) == 1
    assert "approved registry package" in str(errors[0])
    assert manager.get_package(consumer_id) is None
    assert consumer_id not in config.plugins.packages
    assert not (user_root / consumer_id).exists()
    replacement_state = manager.get_package(library_id)
    assert replacement_state is not None
    assert replacement_state.manifest.version == "2.0.0"
    assert (user_root / library_id / "__init__.py").read_text(
        encoding="utf-8"
    ) == 'MARKER = "replacement"\n'


def test_sync_unload_does_not_hold_lock_while_async_shutdown_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig()
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )
    plugin_id = "shutdown-lock-test"
    manifest = PluginManifest(
        id=plugin_id,
        name="Shutdown Lock Test",
        version="1.0.0",
        source="external",
    )
    manager._package_states[plugin_id] = PluginPackageState(
        manifest=manifest,
        enabled=True,
        trusted=True,
        loaded=True,
    )
    shutdown_completed = threading.Event()

    class ReentrantShutdownPlugin(Plugin):
        async def shutdown(self) -> None:
            import asyncio

            await asyncio.to_thread(manager.scan, persist_discovery=False)
            shutdown_completed.set()

    connection = manager.connection_store.create(plugin_id, display_name="Manual fixture", enabled=True)
    instance = ReentrantShutdownPlugin()
    instance.configure(manifest=manifest, connection=connection, context=manager.connection_store.context(connection.connection_id))
    manager._plugin_instances[connection.connection_id] = instance
    manager._instance_packages[connection.connection_id] = plugin_id

    manager.unload_plugin(plugin_id)

    assert shutdown_completed.wait(timeout=2)


def test_package_read_snapshot_does_not_interleave_lifecycle_write(
    tmp_path: Path,
) -> None:
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )
    manager._package_states["existing"] = PluginPackageState(
        manifest=PluginManifest(
            id="existing",
            name="Existing",
            version="1.0.0",
            source="external",
        )
    )
    reader_holds_lock = threading.Event()
    release_reader = threading.Event()
    writer_finished = threading.Event()
    original_values = manager._package_states.values

    class _BlockingValues:
        def __iter__(self):
            reader_holds_lock.set()
            if not release_reader.wait(timeout=5):
                raise TimeoutError("Timed out waiting to release package snapshot")
            return iter(original_values())

    class _BlockingStateDict(dict):
        def values(self):
            return _BlockingValues()

    manager._package_states = _BlockingStateDict(manager._package_states)

    read_result: list[list[PluginPackageState]] = []
    reader = threading.Thread(
        target=lambda: read_result.append(manager.list_packages()),
        daemon=True,
    )

    def write_state() -> None:
        with manager._lifecycle_write_lock:
            manager._package_states["new"] = PluginPackageState(
                manifest=PluginManifest(
                    id="new",
                    name="New",
                    version="1.0.0",
                    source="external",
                )
            )
        writer_finished.set()

    writer = threading.Thread(target=write_state, daemon=True)
    reader.start()
    assert reader_holds_lock.wait(timeout=5)
    writer.start()
    assert writer_finished.wait(timeout=0.05) is False
    release_reader.set()
    reader.join(timeout=5)
    writer.join(timeout=5)

    assert reader.is_alive() is False
    assert writer.is_alive() is False
    assert writer_finished.is_set()
    assert [state.manifest.plugin_id for state in read_result[0]] == ["existing"]


def test_plugin_import_waits_for_explicit_connection(
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
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )

    installed = manager.install_plugin_from_directory(incoming_dir)
    assert installed.enabled is False
    assert installed.loaded is False
    assert manager.connection_store.list("new-rollback-test") == []

    manager.authorize_package("new-rollback-test", expected_package_sha256=PluginSettings.model_validate(config.plugins.packages["new-rollback-test"]).package_sha256)
    with pytest.raises(RuntimeError, match="new plugin failed to load"):
        manager.create_connection("new-rollback-test", display_name="Broken account", enabled=True)

    assert (user_root / "new-rollback-test").is_dir()
    assert "new-rollback-test" in config.plugins.packages
    assert manager.get_package("new-rollback-test") is not None
    assert not [plugin for plugin in manager.iter_loaded_plugins() if plugin.plugin_id == "new-rollback-test"]
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
        trusted=True,
        source="external",
        manifest_path=str(existing_dir / "plugin.toml"),
        official=False,
    )
    existing_manifest = load_plugin_manifest(
        existing_dir / "plugin.toml",
        source="external",
    )
    update_kwargs = _configure_registry_update(
        config,
        installed_manifest=existing_manifest,
        incoming_dir=incoming_dir,
    )
    original_config = config.plugins.packages["update-rollback-test"].model_dump(mode="json")
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)

    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager.scan(persist_discovery=False)
    connection = _connect(manager, "update-rollback-test")
    manager.activate_enabled_plugins()
    assert manager.get_connection_plugin(connection.connection_id).marker == "old-version"

    with pytest.raises(RuntimeError, match="new plugin failed to load"):
        manager.install_plugin_from_directory(
            incoming_dir,
            **update_kwargs,
        )

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
    assert manager.get_connection_plugin(connection.connection_id).marker == "old-version"
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
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
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


def test_local_directory_install_does_not_replace_an_existing_package_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    plugin_id = "local-update-test"
    existing_dir = _write_install_test_plugin(
        user_root,
        plugin_id=plugin_id,
        version="1.0.0",
        marker="existing",
    )
    incoming_dir = _write_install_test_plugin(
        tmp_path / "incoming",
        plugin_id=plugin_id,
        version="2.0.0",
        marker="replacement",
    )
    config = AppConfig()
    config.plugins.packages[plugin_id] = PluginSettings(
        source="external",
        manifest_path=str(existing_dir / "plugin.toml"),
    )
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    manager.scan(persist_discovery=False)

    with pytest.raises(ValueError, match="Cannot replace an installed plugin"):
        manager.install_plugin_from_directory(incoming_dir)

    assert 'version = "1.0.0"' in (existing_dir / "plugin.toml").read_text(encoding="utf-8")
    assert 'marker = "existing"' in (existing_dir / "plugin.py").read_text(encoding="utf-8")


def test_uninstall_refuses_a_package_from_a_custom_scan_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    custom_root = tmp_path / "custom"
    plugin_id = "custom-source"
    plugin_dir = _write_install_test_plugin(
        custom_root,
        plugin_id=plugin_id,
        version="1.0.0",
        marker="keep",
    )
    config = AppConfig()
    config.plugins.packages[plugin_id] = PluginSettings(
        source="external",
        manifest_path=str(plugin_dir / "plugin.toml"),
    )
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: managed_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[custom_root],
    )
    manager.scan(persist_discovery=False)

    with pytest.raises(ValueError, match="managed plugin directory"):
        manager.uninstall_plugin(plugin_id)

    assert plugin_dir.exists()
    assert manager.get_package(plugin_id) is not None
    assert plugin_id in config.plugins.packages


def test_uninstall_refuses_a_manifest_at_the_managed_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    manifest_path = managed_root / "plugin.toml"
    manifest_path.write_text(
        '[plugin]\nprotocol_version = 2\nmin_sdk_version = "0.2.0"\nexecution_mode = "trusted_process"\nid = "root-owned"\nname = "Root Owned"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    sentinel = managed_root / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    config = AppConfig()
    config.plugins.packages["root-owned"] = PluginSettings(
        source="external",
        manifest_path=str(manifest_path),
    )
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: managed_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[managed_root],
    )
    manager._package_states["root-owned"] = PluginPackageState(
        manifest=load_plugin_manifest(manifest_path, source="external")
    )

    with pytest.raises(ValueError, match="managed plugin directory"):
        manager.uninstall_plugin("root-owned")

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert manifest_path.exists()


def test_uninstall_refuses_a_symlinked_managed_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    external_root = tmp_path / "external"
    plugin_id = "linked-package"
    real_dir = _write_install_test_plugin(
        external_root,
        plugin_id=plugin_id,
        version="1.0.0",
        marker="keep",
    )
    managed_root.mkdir()
    linked_dir = managed_root / plugin_id
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    config = AppConfig()
    config.plugins.packages[plugin_id] = PluginSettings(
        source="external",
        manifest_path=str(linked_dir / "plugin.toml"),
    )
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: managed_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[managed_root],
    )
    manifest = load_plugin_manifest(linked_dir / "plugin.toml", source="external")
    manager._package_states[plugin_id] = PluginPackageState(manifest=manifest)

    with pytest.raises(ValueError, match="managed plugin directory"):
        manager.uninstall_plugin(plugin_id)

    assert linked_dir.is_symlink()
    assert real_dir.exists()


def test_uninstall_removes_an_exact_managed_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    plugin_id = "managed-package"
    plugin_dir = _write_install_test_plugin(
        managed_root,
        plugin_id=plugin_id,
        version="1.0.0",
        marker="remove",
    )
    config = AppConfig()
    config.plugins.packages[plugin_id] = PluginSettings(
        source="external",
        manifest_path=str(plugin_dir / "plugin.toml"),
    )
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: managed_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[managed_root],
    )
    manager.scan(persist_discovery=False)

    manager.uninstall_plugin(plugin_id)

    assert not plugin_dir.exists()
    assert manager.get_package(plugin_id) is None
    assert plugin_id not in config.plugins.packages


def test_enable_rejects_a_package_that_does_not_match_persisted_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    custom_root = tmp_path / "custom"
    plugin_id = "identity-mismatch"
    plugin_dir = _write_install_test_plugin(
        custom_root,
        plugin_id=plugin_id,
        version="1.0.0",
        marker="external",
    )
    config = AppConfig()
    config.plugins.packages[plugin_id] = PluginSettings(
        trusted=False,
        source="builtin",
        official=True,
        install_origin="registry",
        registry_source="https://example.test/registry.json",
        registry_repo_url="https://github.com/example/plugins.git",
        package_sha256=compute_package_sha256(plugin_dir),
        installed_package_sha256=compute_installed_package_sha256(plugin_dir),
    )
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: managed_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[custom_root],
    )
    manager.scan(persist_discovery=False)

    with pytest.raises(RuntimeError, match="source does not match"):
        manager.create_connection(plugin_id, display_name="Rejected", enabled=True)

    configured = config.plugins.packages[plugin_id]
    assert configured.source == "builtin"
    assert configured.manifest_path is None
    assert "settings" not in configured.model_dump()
    assert not [plugin for plugin in manager.iter_loaded_plugins() if plugin.plugin_id == plugin_id]
    assert plugin_dir.exists()


def test_enable_does_not_load_when_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plugin_id = "enable-persistence-failure"
    plugin_dir = _write_install_test_plugin(
        tmp_path,
        plugin_id=plugin_id,
        version="1.0.0",
        marker="must-not-load",
    )
    config = AppConfig()
    config.plugins.packages[plugin_id] = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=str(plugin_dir / "plugin.toml"),
    )
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda _updates: False)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[tmp_path],
    )
    manager.scan(persist_discovery=False)

    def fail_persistence(_registry):
        raise RuntimeError("Connection persistence failed")
    monkeypatch.setattr(manager.connection_store, "_write", fail_persistence)
    with pytest.raises(RuntimeError, match="Connection persistence failed"):
        manager.create_connection(plugin_id, display_name="Rejected", enabled=True)

    state = manager.get_package(plugin_id)
    assert state is not None
    assert state.enabled is False
    assert state.trusted is True
    assert manager.connection_store.list() == []
    assert not [plugin for plugin in manager.iter_loaded_plugins() if plugin.plugin_id == plugin_id]


def test_local_install_rejects_unbound_package_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-plugins"
    incoming = _write_install_test_consumer(
        tmp_path / "incoming",
        plugin_id="local-dependent-plugin",
        library_id="shared-library",
    )
    config = AppConfig()
    _patch_plugin_config(monkeypatch, config)
    monkeypatch.setattr(package_files_module, "user_plugins_root", lambda: user_root)
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )

    with pytest.raises(ValueError, match="installed from the marketplace"):
        manager.install_plugin_from_directory(incoming)

    assert manager.get_package("local-dependent-plugin") is None
    assert "local-dependent-plugin" not in config.plugins.packages
    assert not (user_root / "local-dependent-plugin").exists()


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


def test_replace_plugin_directory_keeps_original_when_before_swap_fails(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "marker.txt").write_text("new", encoding="utf-8")
    dest_dir = tmp_path / "installed"
    dest_dir.mkdir()
    (dest_dir / "marker.txt").write_text("old", encoding="utf-8")
    rollback_called = False

    def fail_before_swap() -> None:
        raise RuntimeError("unload failed")

    def record_rollback() -> None:
        nonlocal rollback_called
        rollback_called = True

    with pytest.raises(RuntimeError, match="unload failed"):
        replace_plugin_directory(
            source_dir,
            dest_dir,
            before_swap=fail_before_swap,
            after_rollback=record_rollback,
        )

    assert rollback_called is True
    assert (dest_dir / "marker.txt").read_text(encoding="utf-8") == "old"


def test_replace_plugin_directory_keeps_original_when_backup_rename_fails(
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
    rollback_called = False

    def fail_backup_rename(self: Path, target: Path) -> Path:
        if self == dest_dir and "-backup-" in target.name:
            raise OSError("backup rename failed")
        return original_replace(self, target)

    def record_rollback() -> None:
        nonlocal rollback_called
        rollback_called = True

    monkeypatch.setattr(Path, "replace", fail_backup_rename)

    with pytest.raises(OSError, match="backup rename failed"):
        replace_plugin_directory(
            source_dir,
            dest_dir,
            before_swap=lambda: None,
            after_rollback=record_rollback,
        )

    assert rollback_called is True
    assert (dest_dir / "marker.txt").read_text(encoding="utf-8") == "old"


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
        trusted=True,
        source="external",
        manifest_path=str(tmp_path / "external-tool" / "plugin.toml"),
    )

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True
    )
    monkeypatch.setattr("magi.plugins.manager._resolve_search_paths", lambda: [tmp_path])

    bindings = build_plugin_runtime(
        tool_registry=shared_tool_registry,
        request_source_schedule_refresh=lambda: None,
        source_registry=SourceRegistry(),
        instance_factory=instantiate_fixture_plugin,
    )
    connection = bindings.plugin_manager.create_connection(
        "external-tool", display_name="Runtime account", enabled=True,
    )
    try:
        assert f"{connection.connection_id}:external-hello" in shared_tool_registry.list_tools()
    finally:
        bindings.plugin_manager.unload_plugin("external-tool")


def test_plugin_projection_service_collects_temporal_summary_features_from_loaded_plugins(tmp_path) -> None:
    class ChromeFeaturePlugin(Plugin):
        def build_temporal_summary_features(
            self, *, source_type, events, summary_category, period_start, period_end, budget=None
        ):  # type: ignore[no-untyped-def]
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

    plugin = bind_fixture_plugin(ChromeFeaturePlugin(), "chrome-history", root=tmp_path, source_types=["chrome_history"])
    service = PluginProjectionService(iter_loaded_plugins=lambda: [plugin])

    features = service.build_temporal_summary_features(
        events=[
            {
                "event_id": "evt-1",
                "source": "chrome_history",
                "content": "OpenAI docs",
                "metadata_json": {
                    "source_connection_id": plugin.connection_id, "source_plugin_id": plugin.plugin_id,
                    "source_object_version": "v1",
                    "source_evidence_ref": {"resource_id": "evidence", "connection_id": plugin.connection_id, "version": "v1"},
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
                    "source_connection_id": plugin.connection_id, "source_plugin_id": plugin.plugin_id,
                    "source_object_version": "v1",
                    "source_evidence_ref": {"resource_id": "evidence", "connection_id": plugin.connection_id, "version": "v1"},
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
                    "source_connection_id": plugin.connection_id, "source_plugin_id": plugin.plugin_id,
                    "source_object_version": "v1",
                    "source_evidence_ref": {"resource_id": "evidence", "connection_id": plugin.connection_id, "version": "v1"},
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

    actual = features[f"{plugin.connection_id}:chrome_history"]
    assert actual.pop("projection")["rule_revision"] == "1.0.0"
    assert actual.pop("source_type") == "chrome_history"
    assert {"chrome_history": actual} == {
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


def test_plugin_projection_service_collects_extraction_profiles_from_loaded_plugins(tmp_path) -> None:
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

    plugin = bind_fixture_plugin(SourceProfilePlugin(), "example", root=tmp_path, source_types=["example"])
    service = PluginProjectionService(iter_loaded_plugins=lambda: [plugin])

    profiles = service.iter_extraction_profiles()

    assert len(profiles) == 1
    assert profiles[0].profile_id == "source.example"
    assert profiles[0].source_types == ["example"]


def test_plugin_projection_service_passes_temporal_feature_budget_to_new_hooks(tmp_path) -> None:
    class BudgetAwarePlugin(Plugin):
        def build_temporal_summary_features(
            self, *, source_type, events, summary_category, period_start, period_end, budget=None
        ):  # type: ignore[no-untyped-def]
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

    plugin = bind_fixture_plugin(BudgetAwarePlugin(), "music", root=tmp_path, source_types=["music"])
    service = PluginProjectionService(iter_loaded_plugins=lambda: [plugin])

    features = service.build_temporal_summary_features(
        events=[{"event_id": "evt-1", "source": "music", "content": "song", "metadata_json": {
            "source_connection_id": plugin.connection_id, "source_plugin_id": plugin.plugin_id,
            "source_object_version": "v1",
            "source_evidence_ref": {"resource_id": "evidence", "connection_id": plugin.connection_id, "version": "v1"},
        }}],
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

    assert features[f"{plugin.connection_id}:music"]["total_event_count"] == 10
    assert features[f"{plugin.connection_id}:music"]["covered_event_count"] == 4
    assert features[f"{plugin.connection_id}:music"]["omitted_event_count"] == 6
