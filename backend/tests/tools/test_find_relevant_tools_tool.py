"""Unit tests for FindRelevantToolsTool."""

from __future__ import annotations

import pytest


class TestFindRelevantToolsTool:
    @pytest.mark.asyncio
    async def test_tool_recommends_against_bound_registry_not_global(self, monkeypatch) -> None:
        import magi.tools.builtin.find_relevant_tools_tool as find_tools_module
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.builtin.weather_tool import WeatherTool
        from magi.tools.registry import ToolRegistry
        from magi.tools.schema import ToolExecutionContext

        # Keep the module-level singleton empty to prove the tool uses the
        # registry instance it was registered into.
        monkeypatch.setattr(find_tools_module, "tool_registry", ToolRegistry())

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(WeatherTool)
        tool = registry.get_tool("find-relevant-tools")

        assert tool is not None
        result = await tool.execute(
            {
                "query": "I already know the trip was in Hangzhou on 2025-05-01 and now I need the weather.",
                "current_tools": ["memory_query"],
                "limit": 1,
            },
            ToolExecutionContext(agent_id="test-agent", permissions=["authenticated"]),
        )

        assert result.success is True
        assert result.data["recommended_tools"] == ["weather"]
        assert result.data["tool_expansion"]["append_tools"] == ["weather"]