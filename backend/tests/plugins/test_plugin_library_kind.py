"""Tests for Phase A library/dep plumbing.

Covers the four invariants Phase A introduces:
1. Library packages (``kind == "library"``) are not instantiated as Plugin
   subclasses but still pass discovery + persist-as-enabled.
2. A consumer plugin can import a sibling library module after the manager
   injects the dep's install-root parent onto ``sys.path``.
3. One plugin's load failure (e.g. missing dep) does NOT abort
   ``activate_enabled_plugins`` — other plugins still come up.
4. Uninstall is refcount-aware: libraries with consumers are protected,
   and orphaned libraries are garbage-collected when their last consumer
   leaves.

Patterns follow the existing test_plugin_manager.py helpers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins.manager import PluginManager
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry


# --- helpers -----------------------------------------------------------------


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


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: AppConfig) -> None:
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr(
        "magi.plugins.manager.save_config",
        lambda updates: _apply_updates(config, updates) or True,
    )


def _make_manager(search_path: Path) -> PluginManager:
    return PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        search_paths=[search_path],
        request_sensor_schedule_refresh=lambda: None,
    )


def _write_library(base: Path, *, lib_id: str, module_attr: str = "SENTINEL") -> None:
    """A library package: plugin.toml with kind='library' + python module."""
    lib_dir = base / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "plugin.toml").write_text(
        f"""
[plugin]
id = "{lib_id}"
name = "Library Under Test"
version = "1.0.0"
description = "Shared library for tests"
author = "Test"
official = false
kind = "library"
contribution_types = []
""".strip(),
        encoding="utf-8",
    )
    # The library module itself — importable as `import <lib_id>`.
    (lib_dir / "__init__.py").write_text(
        f'{module_attr} = "from-library"\n',
        encoding="utf-8",
    )


def _write_consumer(
    base: Path,
    *,
    plugin_id: str,
    lib_id: str,
    expected_attr: str = "SENTINEL",
) -> None:
    """A plugin that imports the library and exposes a tool reporting it."""
    plugin_dir = base / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        f"""
[plugin]
id = "{plugin_id}"
name = "Consumer"
version = "1.0.0"
description = "Plugin that imports the library"
author = "Test"
entry_module = "plugin"
entry_class = "ConsumerPlugin"
official = false
contribution_types = ["tool"]
depends_on = ["{lib_id}"]
""".strip(),
        encoding="utf-8",
    )
    # Top-level import — proves the manager put the right dir on sys.path.
    (plugin_dir / "plugin.py").write_text(
        f"""from magi_plugin_sdk import Plugin
from magi_plugin_sdk.tools import Tool, ToolSchema, ToolExecutionContext, ToolResult
from {lib_id} import {expected_attr} as _value


class ReportTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="report-from-library",
            description="returns the value imported from the library",
            category="test",
        )

    async def execute(self, parameters, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(success=True, data={{"value": _value}})


class ConsumerPlugin(Plugin):
    captured = _value

    def get_tools(self):
        return [ReportTool]
""".strip(),
        encoding="utf-8",
    )


def _write_broken_plugin(base: Path, *, plugin_id: str) -> None:
    """A plugin that imports a missing module — fails at exec_module time."""
    plugin_dir = base / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        f"""
[plugin]
id = "{plugin_id}"
name = "Broken"
version = "1.0.0"
description = "Imports a module that doesn't exist"
author = "Test"
entry_module = "plugin"
entry_class = "BrokenPlugin"
official = false
contribution_types = ["tool"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """from magi_plugin_sdk import Plugin
import nonexistent_module_for_test  # noqa: F401  -- intentional failure


class BrokenPlugin(Plugin):
    def get_tools(self):
        return []
""".strip(),
        encoding="utf-8",
    )


def _write_simple_tool_plugin(base: Path, *, plugin_id: str, tool_name: str) -> None:
    """A self-contained tool plugin used to verify other plugins still load
    after one of their neighbors fails."""
    plugin_dir = base / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        f"""
[plugin]
id = "{plugin_id}"
name = "Simple"
version = "1.0.0"
description = "Self-contained tool plugin"
author = "Test"
entry_module = "plugin"
entry_class = "SimplePlugin"
official = false
contribution_types = ["tool"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        f"""from magi_plugin_sdk import Plugin
from magi_plugin_sdk.tools import Tool, ToolSchema, ToolExecutionContext, ToolResult


class SimpleTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="{tool_name}",
            description="simple",
            category="test",
        )

    async def execute(self, parameters, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(success=True, data={{}})


class SimplePlugin(Plugin):
    def get_tools(self):
        return [SimpleTool]
""".strip(),
        encoding="utf-8",
    )


# --- tests -------------------------------------------------------------------


def test_library_is_persisted_as_enabled_and_trusted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Newly-discovered library packages must default to enabled+trusted so
    consumers can rely on them without the user having to toggle anything."""
    _write_library(tmp_path, lib_id="testlib_a")
    config = AppConfig()
    _patch_config(monkeypatch, config)

    manager = _make_manager(tmp_path)
    packages = manager.scan(persist_discovery=True)

    assert len(packages) == 1
    assert packages[0].enabled is True
    assert packages[0].trusted is True
    assert packages[0].manifest.kind == "library"


def test_library_load_does_not_instantiate_plugin_class(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Libraries have no entry_class — load_plugin must short-circuit
    instead of trying to instantiate Plugin and crashing."""
    _write_library(tmp_path, lib_id="testlib_b")
    config = AppConfig()
    _patch_config(monkeypatch, config)

    manager = _make_manager(tmp_path)
    manager.scan(persist_discovery=True)
    manager.activate_enabled_plugins()

    state = manager.get_package("testlib_b")
    assert state is not None
    assert state.loaded is True
    assert state.healthy is True
    # No Plugin instance recorded — libraries have nothing to instantiate.
    assert "testlib_b" not in manager._plugin_instances


def test_consumer_with_depends_on_imports_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The core promise of Phase A: a plugin declaring depends_on=[lib_id]
    can do ``import lib_id`` at module top-level after load."""
    _write_library(tmp_path, lib_id="testlib_c", module_attr="GREETING")
    _write_consumer(
        tmp_path,
        plugin_id="consumer-c",
        lib_id="testlib_c",
        expected_attr="GREETING",
    )
    config = AppConfig()
    _patch_config(monkeypatch, config)

    manager = _make_manager(tmp_path)
    manager.scan(persist_discovery=True)
    # Consumer is external/official=false → discovered as disabled. Flip it
    # so activate actually loads it.
    config.plugins.packages["consumer-c"] = PluginSettings(
        enabled=True, trusted=True, source="external", settings={}
    )
    manager.scan(persist_discovery=False)
    manager.activate_enabled_plugins()

    consumer_state = manager.get_package("consumer-c")
    assert consumer_state is not None, "consumer was not discovered"
    assert consumer_state.healthy is True, (
        f"consumer load failed: {consumer_state.last_error!r}"
    )
    instance = manager._plugin_instances["consumer-c"]
    assert instance.captured == "from-library"
    # And the lib's parent dir really did land on sys.path.
    assert str(tmp_path) in sys.path


def test_missing_dep_yields_clear_error_not_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When a plugin declares depends_on=[X] but X isn't installed, the
    error must name the missing dep (not bubble up as ModuleNotFoundError
    from deep inside user code)."""
    _write_consumer(
        tmp_path,
        plugin_id="orphan-consumer",
        lib_id="missing_lib",
        expected_attr="SENTINEL",
    )
    config = AppConfig()
    _patch_config(monkeypatch, config)

    manager = _make_manager(tmp_path)
    manager.scan(persist_discovery=True)
    config.plugins.packages["orphan-consumer"] = PluginSettings(
        enabled=True, trusted=True, source="external", settings={}
    )
    manager.scan(persist_discovery=False)
    # Must not raise — startup keeps going, plugin is marked unhealthy.
    manager.activate_enabled_plugins()

    state = manager.get_package("orphan-consumer")
    assert state is not None
    assert state.healthy is False
    assert state.last_error is not None
    assert "missing_lib" in state.last_error


def test_broken_plugin_does_not_crash_other_plugins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """activate_enabled_plugins must isolate per-plugin failures so one
    broken plugin can't take down the whole runtime startup (the original
    onboarding-crash bug)."""
    _write_broken_plugin(tmp_path, plugin_id="broken-plugin")
    _write_simple_tool_plugin(
        tmp_path, plugin_id="healthy-plugin", tool_name="healthy-hello"
    )
    config = AppConfig()
    _patch_config(monkeypatch, config)

    manager = _make_manager(tmp_path)
    manager.scan(persist_discovery=True)
    config.plugins.packages["broken-plugin"] = PluginSettings(
        enabled=True, trusted=True, source="external", settings={}
    )
    config.plugins.packages["healthy-plugin"] = PluginSettings(
        enabled=True, trusted=True, source="external", settings={}
    )
    manager.scan(persist_discovery=False)
    # Used to raise; now it must complete and leave broken-plugin unhealthy.
    manager.activate_enabled_plugins()

    broken = manager.get_package("broken-plugin")
    healthy = manager.get_package("healthy-plugin")
    assert broken is not None and broken.healthy is False
    assert broken.last_error is not None
    assert healthy is not None and healthy.healthy is True
    assert "healthy-hello" in manager._tool_registry.list_tools()


def test_enable_and_disable_reject_libraries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Libraries have no enable/disable semantics — toggles must error,
    not silently no-op (which would mask programming bugs in callers)."""
    _write_library(tmp_path, lib_id="testlib_d")
    config = AppConfig()
    _patch_config(monkeypatch, config)

    manager = _make_manager(tmp_path)
    manager.scan(persist_discovery=True)

    with pytest.raises(ValueError, match="library"):
        manager.enable_plugin("testlib_d")
    with pytest.raises(ValueError, match="library"):
        manager.disable_plugin("testlib_d")


def test_iter_consumers_finds_dependents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The refcount helper used by uninstall: returns plugin_ids that
    declare the library in their depends_on."""
    _write_library(tmp_path, lib_id="testlib_e")
    _write_consumer(
        tmp_path, plugin_id="consumer-1", lib_id="testlib_e"
    )
    _write_consumer(
        tmp_path, plugin_id="consumer-2", lib_id="testlib_e"
    )
    config = AppConfig()
    _patch_config(monkeypatch, config)

    manager = _make_manager(tmp_path)
    manager.scan(persist_discovery=True)

    consumers = sorted(manager.iter_consumers("testlib_e"))
    assert consumers == ["consumer-1", "consumer-2"]
    # Library that nobody declares → empty list.
    assert manager.iter_consumers("nothing-references-me") == []
