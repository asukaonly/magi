from __future__ import annotations

from pathlib import Path

import pytest

from magi.config.models import AppConfig
from magi.plugins.actions import ActionExecutionContext
from magi.plugins.manager import PluginManager
from magi.plugins.runtime import get_action_registry
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
    action_registry = get_action_registry().__class__()
    repo_plugins = Path(__file__).resolve().parents[2] / "plugins"

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

    assert tool_registry.get_tool("notify-user") is not None
    assert tool_registry.get_tool("send-email") is not None

    action = action_registry.get_action("notify-user")
    assert action is not None
    action_result = await action.execute({"message": "hello"}, ActionExecutionContext(user_id="u1"))
    assert action_result["status"] == "sent"

    tool = tool_registry.get_tool("send-email")
    assert tool is not None
    tool_result = await tool.execute(
        {"to": "user@example.com", "subject": "Hi", "body": "Body"},
        ToolExecutionContext(agent_id="u1"),
    )
    assert tool_result.success is True
    assert tool_result.data["delivery"] == "simulated"
