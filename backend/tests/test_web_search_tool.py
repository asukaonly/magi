"""
Tests for web search tool defaults and provider selection.
"""
from magi.tools.builtin.web_search_tool import WebSearchTool


def test_web_search_tool_is_ready_with_default_duckduckgo() -> None:
    tool = WebSearchTool()

    assert tool.is_ready() is True
    assert "duckduckgo" in tool.get_available_providers()


def test_web_search_tool_registers_duckduckgo_provider_first() -> None:
    tool = WebSearchTool()

    assert tool.get_all_provider_names()[0] == "duckduckgo"
