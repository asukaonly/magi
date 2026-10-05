"""Unit tests for FindRelevantToolsTool."""

from __future__ import annotations

import pytest


def _make_context_with_memory_query(memory_query_port=None, *, env_vars=None):
    """Build a ToolExecutionContext with an injected memory_query port."""
    from magi.tools.schema import ToolExecutionContext
    from magi.core.tool_capabilities import ToolCapabilities

    caps = ToolCapabilities(memory_query=memory_query_port)
    return ToolExecutionContext(
        agent_id="test-agent",
        permissions=["authenticated"],
        env_vars=dict(env_vars or {}),
        capabilities=caps,
    )


class TestFindRelevantToolsTool:
    @pytest.mark.asyncio
    async def test_tool_recommends_against_bound_registry_not_global(self, monkeypatch) -> None:
        import magi.tools.builtin.find_relevant_tools_tool as find_tools_module
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.builtin.weather_tool import WeatherTool
        from magi.tools.registry import ToolRegistry

        # Keep the module-level singleton empty to prove the tool uses the
        # registry instance it was registered into.
        monkeypatch.setattr(find_tools_module, "tool_registry", ToolRegistry())

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(WeatherTool)
        tool = registry.get_tool("find-relevant-tools")

        assert tool is not None
        # No memory_query port needed; the tool falls back gracefully when None.
        result = await tool.execute(
            {
                "query": "I already know the trip was in Hangzhou on 2025-05-01 and now I need the weather.",
                "current_tools": ["memory_query"],
                "limit": 1,
            },
            _make_context_with_memory_query(memory_query_port=None),
        )

        assert result.success is True
        assert result.data["recommended_tools"] == ["weather"]
        assert result.data["tool_expansion"]["append_tools"] == ["weather"]

    @pytest.mark.asyncio
    async def test_tool_discovers_english_calendar_skill_from_chinese_query(self, tmp_path) -> None:
        from magi.tools.builtin.weather_tool import WeatherTool
        from magi.skills.schema import SkillMetadata
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(WeatherTool)
        registry.register_skill_index(
            {
                "calendar-availability": SkillMetadata(
                    name="calendar-availability",
                    description="Find calendar availability, free busy slots, meetings, and schedules.",
                    directory=tmp_path,
                    category="calendar",
                    tags=["calendar", "availability", "schedule"],
                )
            }
        )
        tool = registry.get_tool("find-relevant-tools")

        assert tool is not None
        result = await tool.execute(
            {
                "query": "帮我找能看日程空档和会议安排的能力，也可能需要天气",
                "current_tools": [],
                "limit": 2,
            },
            _make_context_with_memory_query(memory_query_port=None),
        )

        assert result.success is True
        assert set(result.data["recommended_tools"]) == {"calendar-availability", "weather"}
        assert {row["name"]: row["type"] for row in result.data["recommendations"]} == {
            "calendar-availability": "skill",
            "weather": "tool",
        }

        metrics = result.data["discovery_metrics"]
        assert metrics["cache_hit"] is False
        assert metrics["candidate_count"] == 2
        assert metrics["recommended_count"] == 2
        assert metrics["candidate_source_counts"] == {"builtin": 1, "skill": 1}
        assert metrics["recommended_source_counts"] == {"builtin": 1, "skill": 1}

    @pytest.mark.asyncio
    async def test_tool_ranks_matching_skill_ahead_of_generic_tool(self, monkeypatch, tmp_path) -> None:
        from magi.skills.schema import SkillMetadata
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.builtin.web_search_tool import WebSearchTool
        from magi.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(WebSearchTool)
        registry.register_skill_index(
            {
                "calendar-availability": SkillMetadata(
                    name="calendar-availability",
                    description="Find calendar availability, free busy slots, meetings, and schedules.",
                    directory=tmp_path,
                    category="calendar",
                    tags=["calendar", "availability", "schedule"],
                )
            }
        )
        tool = registry.get_tool("find-relevant-tools")

        assert tool is not None

        from unittest.mock import patch
        from magi.tools.discovery_index import ToolDiscoveryIndex

        candidates = [
            {
                "name": "web-search",
                "tool": "web-search",
                "type": "tool",
                "source": "builtin",
                "reason": "generic search",
                "score": 0.2,
            },
            {
                "name": "calendar-availability",
                "type": "skill",
                "source": "skill",
                "reason": "calendar slots",
                "score": 0.8,
            },
        ]
        with patch.object(ToolDiscoveryIndex, "search", return_value=candidates) as search:
            result = await tool.execute(
                {"query": "calendar slots", "limit": 2}, _make_context_with_memory_query()
            )
        assert search.call_count == 1
        assert search.call_args.kwargs["query"] == "calendar slots"
        assert result.success
        assert result.data["recommended_tools"] == ["calendar-availability", "web-search"]
        assert result.data["tool_expansion"]["append_tools"] == ["calendar-availability", "web-search"]

    @pytest.mark.asyncio
    async def test_advisory_both_reranks_available_candidates_and_excludes_open_breakers(self):
        from unittest.mock import AsyncMock, patch
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.builtin.web_search_tool import WebSearchTool
        from magi.tools.builtin.web_fetch_tool import WebFetchTool
        from magi.tools.builtin.weather_tool import WeatherTool
        from magi.tools.discovery_index import ToolDiscoveryIndex
        from magi.tools.registry import ToolRegistry
        from types import SimpleNamespace

        registry = ToolRegistry()
        for cls in [FindRelevantToolsTool, WebSearchTool, WebFetchTool, WeatherTool]:
            registry.register(cls)
        tool = registry.get_tool("find-relevant-tools")
        candidates = [
            {
                "name": name,
                "tool": name,
                "type": "tool",
                "source": "builtin",
                "score": score,
                "reason": "lookup",
            }
            for name, score in [("web-search", 0.99), ("web-fetch", 0.82), ("weather", 0.61)]
        ]
        advisory = AsyncMock(
            return_value=[
                {"tool_name": "web-search", "available": False, "breaker_state": "open"},
                {
                    "tool_name": "weather",
                    "available": True,
                    "context_fit": 0.92,
                    "success_rate": 0.94,
                    "total_attempts": 9,
                    "strategy_hint": "Use the known date and city",
                },
            ]
        )
        params = {"query": "weather lookup", "limit": 2}
        with patch.object(ToolDiscoveryIndex, "search", return_value=candidates) as search:
            baseline = await tool.execute(
                params, _make_context_with_memory_query(env_vars={"session_id": "baseline"})
            )
            result = await tool.execute(
                params,
                _make_context_with_memory_query(
                    SimpleNamespace(get_tool_advisory=advisory), env_vars={"session_id": "advised"}
                ),
            )
        assert search.call_count == 2
        assert baseline.success and result.success
        assert baseline.data["recommended_tools"] == ["web-search", "web-fetch"]
        assert result.data["recommended_tools"] == ["weather", "web-fetch"]
        assert result.data["tool_expansion"]["append_tools"] == ["weather", "web-fetch"]
        advisory.assert_awaited_once_with(
            tool_names=["web-search", "web-fetch", "weather"], task_context="weather lookup"
        )
        winner = result.data["recommendations"][0]
        assert winner["score"] > 0.82
        assert winner["l4_advisory"]["context_fit"] == 0.92

    @pytest.mark.asyncio
    async def test_tool_discovery_filters_tools_not_allowed_by_context_permissions(self) -> None:
        from magi.tools.builtin.bash_tool import BashTool
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(BashTool)
        tool = registry.get_tool("find-relevant-tools")

        assert tool is not None

        params = {"query": "run a shell command to inspect the local project", "limit": 1}
        context = _make_context_with_memory_query(env_vars={"session_id": "permission-check"})
        context.permissions.append("dangerous_tools")
        allowed = await tool.execute(params, context)
        context.permissions.remove("dangerous_tools")
        denied = await tool.execute(params, context)
        assert allowed.success and denied.success
        assert allowed.data["recommended_tools"] == ["bash"]
        assert denied.data["recommended_tools"] == []
        assert denied.data["tool_expansion"]["append_tools"] == []
        assert denied.data["discovery_metrics"]["cache_hit"] is False
        assert denied.data["discovery_metrics"]["candidate_count"] == 1

    @pytest.mark.asyncio
    async def test_tool_discovers_readonly_mcp_tool(self) -> None:
        from magi.mcp.tool_adapter import build_adapter_class
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(
            build_adapter_class(
                server_id="calendar",
                remote={
                    "name": "list_events",
                    "description": "List calendar events and meeting availability.",
                    "inputSchema": {"type": "object", "properties": {}},
                    "annotations": {"readOnlyHint": True},
                },
                manager=None,
                call_timeout_ms=1000,
                override=None,
            )
        )
        tool = registry.get_tool("find-relevant-tools")

        assert tool is not None
        result = await tool.execute(
            {
                "query": "calendar meeting availability",
                "current_tools": [],
                "limit": 1,
            },
            _make_context_with_memory_query(memory_query_port=None),
        )

        assert result.success is True
        assert result.data["recommended_tools"] == ["mcp__calendar__list_events"]
        assert result.data["recommendations"][0]["source"] == "mcp"


    @pytest.mark.asyncio
    async def test_tool_discovery_reuses_same_session_cache(self, monkeypatch) -> None:
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.builtin.weather_tool import WeatherTool
        from magi.tools.discovery_index import ToolDiscoveryIndex
        from magi.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(WeatherTool)
        tool = registry.get_tool("find-relevant-tools")
        assert tool is not None

        call_count = 0
        original_search = ToolDiscoveryIndex.search

        def _counting_search(self, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_search(self, **kwargs)

        monkeypatch.setattr(ToolDiscoveryIndex, "search", _counting_search)
        ctx = _make_context_with_memory_query(
            memory_query_port=None,
            env_vars={"session_id": "session-cache"},
        )
        params = {
            "query": "weather forecast for a city",
            "current_tools": [],
            "limit": 1,
        }

        first = await tool.execute(params, ctx)
        second = await tool.execute(params, ctx)

        assert first.data["recommended_tools"] == ["weather"]
        assert second.data["recommended_tools"] == ["weather"]
        assert first.data["discovery_metrics"]["cache_hit"] is False
        assert second.data["discovery_metrics"]["cache_hit"] is True
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_tool_discovery_cache_invalidates_when_registry_changes(self, monkeypatch, tmp_path) -> None:
        from magi.skills.schema import SkillMetadata
        from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
        from magi.tools.builtin.weather_tool import WeatherTool
        from magi.tools.discovery_index import ToolDiscoveryIndex
        from magi.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FindRelevantToolsTool)
        registry.register(WeatherTool)
        tool = registry.get_tool("find-relevant-tools")
        assert tool is not None

        call_count = 0
        original_search = ToolDiscoveryIndex.search

        def _counting_search(self, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_search(self, **kwargs)

        monkeypatch.setattr(ToolDiscoveryIndex, "search", _counting_search)
        ctx = _make_context_with_memory_query(
            memory_query_port=None,
            env_vars={"session_id": "session-registry-change"},
        )
        params = {
            "query": "weather forecast",
            "current_tools": [],
            "limit": 1,
        }

        first = await tool.execute(params, ctx)
        registry.register_skill_index(
            {
                "weather-planning": SkillMetadata(
                    name="weather-planning",
                    description="Plan around weather and forecast constraints.",
                    directory=tmp_path,
                    category="planning",
                    tags=["weather", "forecast"],
                )
            }
        )
        second = await tool.execute(params, ctx)

        assert first.data["discovery_metrics"]["cache_hit"] is False
        assert second.data["discovery_metrics"]["cache_hit"] is False
        assert call_count == 2
