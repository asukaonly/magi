"""
Tests for web-fetch tool behavior and fallback logic.
"""
from types import MethodType, SimpleNamespace

import pytest

from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.web_fetch.curl_fetch import CurlFetchProvider
from magi.tools.schema import ToolExecutionContext, ToolResult, ToolErrorCode


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


@pytest.mark.asyncio
async def test_invalid_url_returns_error():
    tool = WebFetchTool()
    result = await tool.execute({"url": "example.com"}, _context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_URL.value


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


@pytest.mark.asyncio
async def test_web_fetch_passes_configured_proxy_to_provider(monkeypatch):
    tool = WebFetchTool()
    captured = {}

    monkeypatch.setattr(
        "magi.tools.builtin.web_fetch_tool.get_config",
        lambda: SimpleNamespace(network=SimpleNamespace(proxy_url=lambda: "socks5://127.0.0.1:7890")),
    )

    async def fake_execute_with_provider(self, provider_name, params):
        captured["provider_name"] = provider_name
        captured["params"] = params
        return ToolResult(
            success=True,
            data={
                "provider": provider_name,
                "url": params["url"],
                "final_url": params["url"],
                "status_code": 200,
                "content_type": "text/html",
                "title": "Doc",
                "html": "<html><body><p>ok</p></body></html>",
                "rendered": False,
            },
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"url": "https://example.com", "mode": "http"}, _context())

    assert result.success is True
    assert captured["provider_name"] == "http"
    assert captured["params"]["proxy_url"] == "socks5://127.0.0.1:7890"


@pytest.mark.asyncio
async def test_curl_fetch_ignores_environment_proxy_when_disabled(monkeypatch):
    provider = CurlFetchProvider()
    captured = {}

    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:7890")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"<html><body>ok</body></html>", b""

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(
        "magi.tools.providers.web_fetch.curl_fetch.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await provider.execute(
        {"url": "https://example.com", "timeout_ms": 15000, "proxy_url": None},
        ProviderConfig(),
    )

    assert result["provider"] == "curl"
    assert "--noproxy" in captured["command"]
    assert captured["env"].get("HTTP_PROXY") is None
