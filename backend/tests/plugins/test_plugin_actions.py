from __future__ import annotations

from pathlib import Path

import pytest

from magi.config.models import AppConfig
from magi.plugins.actions import ActionExecutionContext, ActionRegistry
from magi.plugins.manager import PluginManager
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolExecutionContext


@pytest.mark.asyncio
async def test_core_actions_plugin_registers_actions_and_tool_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig()
    tool_registry = ToolRegistry()
    sensor_registry = SensorRegistry()
    action_registry = ActionRegistry()
    repo_plugins = Path(__file__).resolve().parents[3] / "plugins"

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", lambda updates: True)

    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=sensor_registry,
        action_registry=action_registry,
        search_paths=[repo_plugins],
    )

    manager.scan(persist_discovery=False)
    manager.load_plugin("core-actions")

    assert tool_registry.get_tool("notify-user") is None
    assert tool_registry.get_tool("send-email") is not None

    action = action_registry.get_action("notify-user")
    assert action is None

    tool = tool_registry.get_tool("send-email")
    assert tool is not None
    tool_result = await tool.execute(
        {"to": "user@example.com", "subject": "Hi", "body": "Body"},
        ToolExecutionContext(agent_id="u1"),
    )
    assert tool_result.success is True
    assert tool_result.data["delivery"] == "simulated"
