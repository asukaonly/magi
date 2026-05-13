from types import MethodType, SimpleNamespace

import pytest

from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.schema import ToolExecutionContext, ToolResult
from magi.i18n import language_context


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


def _fake_config(proxy_url: str | None):
    return SimpleNamespace(
        network=SimpleNamespace(proxy_url=lambda: proxy_url),
    )


@pytest.mark.asyncio
async def test_web_search_passes_configured_proxy_to_provider(monkeypatch):
    tool = WebSearchTool()
    captured = {}

    monkeypatch.setattr(
        "magi.tools.builtin.web_search_tool.get_config",
        lambda: _fake_config("http://127.0.0.1:7890"),
    )
    tool._get_default_provider = lambda: "duckduckgo"
    tool.get_available_providers = lambda: ["duckduckgo"]

    async def fake_execute_with_provider(self, provider_name, params):
        captured["provider_name"] = provider_name
        captured["params"] = params
        return ToolResult(success=True, data={})

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"query": "magi", "num_results": 3}, _context())

    assert result.success is True
    assert captured["provider_name"] == "duckduckgo"
    assert captured["params"]["proxy_url"] == "http://127.0.0.1:7890"


@pytest.mark.asyncio
async def test_web_search_does_not_fallback_from_unconfigured_requested_provider(monkeypatch):
    tool = WebSearchTool()
    called = False

    monkeypatch.setattr(
        "magi.tools.builtin.web_search_tool.get_config",
        lambda: _fake_config(None),
    )
    tool._get_default_provider = lambda: "brave"
    tool.get_available_providers = lambda: ["duckduckgo"]

    async def fake_execute_with_provider(self, provider_name, params):
        nonlocal called
        called = True
        _ = (self, provider_name, params)
        return ToolResult(success=True, data={})

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    with language_context("en"):
        result = await tool.execute({"query": "magi"}, _context())

    assert called is False
    assert result.success is False
    assert result.error_code == "PROVIDER_NOT_CONFIGURED"
    assert result.data["requested_provider"] == "brave"
    assert result.data["available_providers"] == ["duckduckgo"]
    assert result.data["retryable"] is False
    assert result.data["terminal"] is True
    assert "DuckDuckGo" not in result.error


@pytest.mark.asyncio
async def test_web_search_duckduckgo_challenge_guidance_uses_current_language(monkeypatch):
    tool = WebSearchTool()

    monkeypatch.setattr(
        "magi.tools.builtin.web_search_tool.get_config",
        lambda: _fake_config(None),
    )
    tool._get_default_provider = lambda: "duckduckgo"
    tool.get_available_providers = lambda: ["duckduckgo"]

    async def fake_execute_with_provider(self, provider_name, params):
        _ = (self, provider_name, params)
        return ToolResult(
            success=False,
            error="DuckDuckGo search challenge triggered by anti-bot verification",
            error_code="PROVIDER_ERROR",
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    with language_context("zh-CN"):
        result = await tool.execute({"query": "magi"}, _context())

    assert result.success is False
    assert result.error_code == "PROVIDER_CHALLENGE"
    assert result.data["retryable"] is False
    assert result.data["terminal"] is True
    assert "反机器人验证" in result.error
    assert "不要在同一个请求里反复重试 DuckDuckGo" in result.data["llm_guidance"]


@pytest.mark.asyncio
async def test_weather_passes_disabled_proxy_as_none(monkeypatch):
    tool = WeatherTool()
    captured = {}

    monkeypatch.setattr(
        "magi.tools.builtin.weather_tool.get_config",
        lambda: _fake_config(None),
    )
    tool._get_default_provider = lambda: "qweather"
    tool.get_available_providers = lambda: ["qweather"]

    async def fake_execute_with_provider(self, provider_name, params):
        captured["provider_name"] = provider_name
        captured["params"] = params
        return ToolResult(success=True, data={})

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"location": "Hangzhou"}, _context())

    assert result.success is True
    assert captured["provider_name"] == "qweather"
    assert captured["params"]["proxy_url"] is None