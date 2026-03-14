from __future__ import annotations

from pathlib import Path

import pytest

from magi.plugins.actions import ActionRegistry
from magi.config.models import AppConfig, PluginSettings
from magi.plugins.manager import PluginManager
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry


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
        """
from magi.plugins import Plugin
from magi.tools import Tool, ToolSchema, ToolExecutionContext, ToolResult

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
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        action_registry=ActionRegistry(),
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
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        action_registry=ActionRegistry(),
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
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: _apply_updates(config, updates) or True)

    builtin_plugins_root = Path(__file__).resolve().parents[3] / "plugins"
    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=SensorRegistry(),
        action_registry=ActionRegistry(),
        search_paths=[builtin_plugins_root],
    )

    packages = manager.scan(persist_discovery=False)
    assert any(item.manifest.plugin_id == "core-tools" for item in packages)

    manager.activate_enabled_plugins()

    assert "memory_query" in tool_registry.list_tools()
