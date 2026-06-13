"""Tests for web-search provider selection: the LLM cannot pick a provider and
the tool falls back deterministically across configured providers."""
from __future__ import annotations

import pytest

import magi.tools.builtin.web_search_tool as web_search_tool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.schema import ToolExecutionContext


class _FakeNet:
    def proxy_url(self):
        return None


class _FakeConfig:
    network = _FakeNet()


class _FakeProvider:
    """Minimal provider stand-in for MultiProviderTool.execute_with_provider."""

    def __init__(self, name: str, *, ready: bool = True, behavior=None) -> None:
        self.name = name
        self._ready = ready
        self._behavior = behavior or (lambda params: {"results": [], "result_count": 1})

    def is_ready(self, config) -> bool:
        return self._ready

    async def execute(self, params, config):
        return self._behavior(params)


def _tool(providers, *, default: str) -> WebSearchTool:
    tool = WebSearchTool()
    tool._providers = {p.name: p for p in providers}
    tool._get_provider_config = lambda name: {}  # type: ignore[assignment]
    tool._get_default_provider = lambda: default  # type: ignore[assignment]
    return tool


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=".")


def _raises(_params):
    raise RuntimeError("provider boom")


def test_schema_exposes_no_provider_parameter() -> None:
    names = {p.name for p in WebSearchTool().schema.parameters}
    assert "provider" not in names  # LLM cannot select a provider
    assert "query" in names


@pytest.mark.asyncio
async def test_uses_configured_default_when_healthy(monkeypatch) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    tool = _tool(
        [_FakeProvider("brave"), _FakeProvider("duckduckgo")],
        default="brave",
    )
    result = await tool.execute({"query": "hello"}, _ctx())
    assert result.success is True
    assert result.data["actual_provider"] == "brave"
    assert result.data["fallback_used"] is False


@pytest.mark.asyncio
async def test_falls_back_when_default_fails(monkeypatch) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    tool = _tool(
        [_FakeProvider("brave", behavior=_raises), _FakeProvider("tavily")],
        default="brave",
    )
    result = await tool.execute({"query": "hello"}, _ctx())
    assert result.success is True
    assert result.data["actual_provider"] == "tavily"
    assert result.data["fallback_used"] is True
    assert result.data["fallback_from"] == ["brave"]


@pytest.mark.asyncio
async def test_ignores_caller_supplied_provider(monkeypatch) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    tool = _tool(
        [_FakeProvider("brave"), _FakeProvider("duckduckgo")],
        default="brave",
    )
    # Even if a stray 'provider' arg sneaks in, it must be ignored: default wins.
    result = await tool.execute({"query": "hello", "provider": "duckduckgo"}, _ctx())
    assert result.success is True
    assert result.data["actual_provider"] == "brave"


@pytest.mark.asyncio
async def test_all_providers_failed_reports_aggregate(monkeypatch) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    tool = _tool(
        [
            _FakeProvider("brave", behavior=_raises),
            _FakeProvider("duckduckgo", behavior=_raises),
        ],
        default="brave",
    )
    result = await tool.execute({"query": "hello"}, _ctx())
    assert result.success is False
    assert set(result.data["attempted_providers"]) == {"brave", "duckduckgo"}
    assert result.data["terminal"] is True
