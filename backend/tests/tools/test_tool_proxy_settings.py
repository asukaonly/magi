from types import MethodType, SimpleNamespace

import pytest

from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.schema import ToolExecutionContext, ToolResult
from magi.i18n import language_context


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


def _turn_context(turn_id: str = "turn_test", agent_id: str = "test-agent") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id=agent_id, env_vars={"turn_id": turn_id})


def _fake_config(proxy_url: str | None):
    return SimpleNamespace(
        network=SimpleNamespace(proxy_url=lambda: proxy_url),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["search", "weather", "fetch"])
@pytest.mark.parametrize("proxy_url", [None, "socks5://127.0.0.1:7890"])
async def test_configured_proxy_is_forwarded_or_explicitly_disabled_at_provider_boundary(
    monkeypatch, kind, proxy_url
):
    from magi.tools.builtin.web_fetch_tool import WebFetchTool
    from unittest.mock import AsyncMock

    classes = {"search": WebSearchTool, "weather": WeatherTool, "fetch": WebFetchTool}
    modules = {"search": "web_search_tool", "weather": "weather_tool", "fetch": "web_fetch_tool"}
    provider = {"search": "duckduckgo", "weather": "qweather", "fetch": "http"}[kind]
    monkeypatch.setattr(
        f"magi.tools.builtin.{modules[kind]}.get_config", lambda: _fake_config(proxy_url)
    )
    tool = classes[kind]()
    if kind != "fetch":
        monkeypatch.setattr(tool, "_get_default_provider", lambda: provider)
        monkeypatch.setattr(tool, "get_available_providers", lambda: [provider])
    else:
        monkeypatch.setattr(
            "magi.tools.builtin.web_fetch_tool.blocked_url_target_reason",
            AsyncMock(return_value=None),
        )
    calls = []

    async def execute_with_provider(provider_name, params):
        calls.append((provider_name, params))
        return ToolResult(
            success=True,
            data={
                "provider": provider_name,
                "url": params.get("url"),
                "final_url": params.get("url"),
                "status_code": 200,
                "content_type": "text/html",
                "title": "Doc",
                "html": "<p>ok</p>",
                "rendered": False,
            },
        )

    monkeypatch.setattr(tool, "execute_with_provider", execute_with_provider)
    params = {
        "search": {"query": "magi"},
        "weather": {"location": "Hangzhou"},
        "fetch": {"url": "https://example.com", "mode": "http"},
    }[kind]
    result = await tool.execute(params, _context())
    assert result.success, result.error
    assert len(calls) == 1
    assert calls[0][0] == provider
    assert "proxy_url" in calls[0][1] and calls[0][1]["proxy_url"] == proxy_url


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
async def test_web_search_same_turn_duplicate_returns_compact_guidance(monkeypatch):
    tool = WebSearchTool()
    calls = 0

    monkeypatch.setattr(
        "magi.tools.builtin.web_search_tool.get_config",
        lambda: _fake_config(None),
    )
    tool._get_default_provider = lambda: "duckduckgo"
    tool.get_available_providers = lambda: ["duckduckgo"]

    async def fake_execute_with_provider(self, provider_name, params):
        nonlocal calls
        calls += 1
        _ = (self, provider_name, params)
        return ToolResult(
            success=True,
            data={
                "result_count": 1,
                "results": [
                    {
                        "title": "Hangzhou Metro",
                        "url": "https://example.com/metro",
                        "description_preview": "route details",
                    }
                ],
            },
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    first = await tool.execute({"query": "杭州 西站 地铁", "num_results": 3}, _turn_context())
    second = await tool.execute({"query": "杭州   西站 地铁", "num_results": 3}, _turn_context())

    assert first.success is True
    assert second.success is True
    assert calls == 1
    assert second.data["duplicate_query"] is True
    assert "results" not in second.data


@pytest.mark.asyncio
async def test_web_search_duplicate_cache_is_scoped_to_execution_agent(monkeypatch):
    tool = WebSearchTool()
    calls = 0

    monkeypatch.setattr(
        "magi.tools.builtin.web_search_tool.get_config",
        lambda: _fake_config(None),
    )
    tool._get_default_provider = lambda: "duckduckgo"
    tool.get_available_providers = lambda: ["duckduckgo"]

    async def fake_execute_with_provider(self, provider_name, params):
        nonlocal calls
        calls += 1
        _ = (self, provider_name, params)
        return ToolResult(success=True, data={"result_count": 1, "results": []})

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    await tool.execute({"query": "杭州 西站 地铁", "num_results": 3}, _turn_context(agent_id="a"))
    await tool.execute({"query": "杭州 西站 地铁", "num_results": 3}, _turn_context(agent_id="b"))

    assert calls == 2
