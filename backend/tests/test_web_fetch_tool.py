"""
Tests for web-fetch tool behavior and fallback logic.
"""
from types import MethodType

import pytest

from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.schema import ToolExecutionContext, ToolResult


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


@pytest.mark.asyncio
async def test_invalid_url_returns_error():
    tool = WebFetchTool()
    result = await tool.execute({"url": "example.com"}, _context())

    assert result.success is False
    assert result.error_code == "INVALID_URL"


@pytest.mark.asyncio
async def test_auto_fallback_uses_browser_for_js_shell():
    tool = WebFetchTool()

    async def fake_execute_with_provider(self, provider_name, params):
        if provider_name == "http":
            return ToolResult(
                success=True,
                data={
                    "provider": "http",
                    "url": params["url"],
                    "final_url": params["url"],
                    "status_code": 200,
                    "content_type": "text/html",
                    "title": "",
                    "html": "<html><body><div id='app'></div><script>a()</script><script>b()</script><script>c()</script></body></html>",
                    "rendered": False,
                },
            )
        if provider_name == "browser":
            return ToolResult(
                success=True,
                data={
                    "provider": "browser",
                    "url": params["url"],
                    "final_url": params["url"],
                    "status_code": 200,
                    "content_type": "text/html",
                    "title": "Rendered Page",
                    "html": "<html><body><h1>Hello</h1><p>Rendered content</p></body></html>",
                    "rendered": True,
                },
            )
        return ToolResult(success=False, error="should not call curl")

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"url": "https://example.com", "mode": "auto"}, _context())

    assert result.success is True
    assert result.data["provider"] == "browser"
    assert result.data["attempts"] == ["http", "browser"]


@pytest.mark.asyncio
async def test_auto_fallback_to_curl_when_browser_fails():
    tool = WebFetchTool()

    async def fake_execute_with_provider(self, provider_name, params):
        if provider_name == "http":
            return ToolResult(
                success=True,
                data={
                    "provider": "http",
                    "url": params["url"],
                    "final_url": params["url"],
                    "status_code": 200,
                    "content_type": "text/html",
                    "title": "",
                    "html": "<html><body><div id='root'></div><script>a()</script><script>b()</script><script>c()</script></body></html>",
                    "rendered": False,
                },
            )
        if provider_name == "browser":
            return ToolResult(success=False, error="playwright missing", error_code="PROVIDER_ERROR")
        if provider_name == "curl":
            return ToolResult(
                success=True,
                data={
                    "provider": "curl",
                    "url": params["url"],
                    "final_url": params["url"],
                    "status_code": None,
                    "content_type": "text/html",
                    "title": "",
                    "html": "<html><body><p>fallback</p></body></html>",
                    "rendered": False,
                },
            )
        return ToolResult(success=False, error="unexpected provider")

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"url": "https://example.com", "mode": "auto"}, _context())

    assert result.success is True
    assert result.data["provider"] == "curl"
    assert result.data["attempts"] == ["http", "browser", "curl"]


@pytest.mark.asyncio
async def test_default_output_is_markdown():
    tool = WebFetchTool()

    async def fake_execute_with_provider(self, provider_name, params):
        return ToolResult(
            success=True,
            data={
                "provider": provider_name,
                "url": params["url"],
                "final_url": params["url"],
                "status_code": 200,
                "content_type": "text/html",
                "title": "Doc",
                "html": "<html><body><h1>Title</h1><p>Paragraph</p></body></html>",
                "rendered": False,
            },
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"url": "https://example.com", "mode": "http"}, _context())

    assert result.success is True
    assert result.data["output_format"] == "markdown"
    assert "# Title" in result.data["content"]
