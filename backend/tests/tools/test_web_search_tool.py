"""
Tests for web search tool defaults and provider selection.
"""
from types import MethodType

import pytest

from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.schema import ToolExecutionContext, ToolResult, ToolErrorCode


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


def test_web_search_tool_is_ready_with_default_duckduckgo() -> None:
    tool = WebSearchTool()

    assert tool.is_ready() is True
    assert "duckduckgo" in tool.get_available_providers()


def test_web_search_tool_registers_duckduckgo_provider_first() -> None:
    tool = WebSearchTool()

    assert tool.get_all_provider_names()[0] == "duckduckgo"


@pytest.mark.asyncio
async def test_web_search_exposes_requested_and_actual_provider_on_fallback() -> None:
    tool = WebSearchTool()

    tool.get_available_providers = MethodType(lambda self: ["duckduckgo"], tool)

    async def fake_execute_with_provider(self, provider_name, params):  # type: ignore[no-untyped-def]
        return ToolResult(
            success=True,
            data={
                "provider": provider_name,
                "results": [{"title": "Example", "url": "https://example.com"}],
                "params": params,
            },
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute(
        {"query": "Hangzhou news", "provider": "brave"},
        _context(),
    )

    assert result.success is True
    assert result.data["requested_provider"] == "brave"
    assert result.data["actual_provider"] == "duckduckgo"
    assert "Requested provider 'brave' is unavailable" in result.data["fallback_reason"]


@pytest.mark.asyncio
async def test_web_search_applies_explicit_date_range_metadata() -> None:
    tool = WebSearchTool()

    async def fake_execute_with_provider(self, provider_name, params):  # type: ignore[no-untyped-def]
        return ToolResult(
            success=True,
            data={
                "provider": provider_name,
                "results": [{"title": "Example", "url": "https://example.com"}],
                "params": params,
            },
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute(
        {
            "query": "Hangzhou important news",
            "start_date": "2026-03-03",
            "end_date": "2026-03-09",
        },
        _context(),
    )

    assert result.success is True
    assert result.data["date_range_applied"] == {
        "start_date": "2026-03-03",
        "end_date": "2026-03-09",
    }
    assert "after:2026-03-03 before:2026-03-09" in result.data["executed_query"]


@pytest.mark.asyncio
async def test_web_search_duckduckgo_challenge_returns_configuration_guidance() -> None:
    tool = WebSearchTool()

    tool.get_available_providers = MethodType(lambda self: ["duckduckgo"], tool)

    async def fake_execute_with_provider(self, provider_name, params):  # type: ignore[no-untyped-def]
        _ = params
        return ToolResult(
            success=False,
            error=(
                "DuckDuckGo search challenge triggered. "
                "The provider returned an anti-bot verification page instead of search results."
            ),
            error_code=ToolErrorCode.PROVIDER_ERROR.value,
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute(
        {"query": "Hangzhou news", "provider": "duckduckgo"},
        _context(),
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.PROVIDER_CHALLENGE.value
    assert result.data["next_action"] == "ask_user_to_configure_search_provider"
    assert result.data["requested_provider"] == "duckduckgo"
    assert result.data["actual_provider"] == "duckduckgo"
    assert "tool.web-search.providers.brave.api_key" in {
        item["path"] for item in result.data["config_examples"]
    }
