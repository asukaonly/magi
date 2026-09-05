"""Tests for web-search provider selection: the LLM cannot pick a provider and
the tool falls back deterministically across configured providers."""
from __future__ import annotations

import pytest

import magi.tools.builtin.web_search_tool as web_search_tool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.http_errors import ProviderRateLimitError
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
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize(
    ("dates", "expected_query", "expected_bounds"),
    [
        ({}, "news", None),
        ({"start_date": "2026-01-01"}, "news after:2026-01-01", {"start_date": "2026-01-01"}),
        ({"end_date": "2026-09-05"}, "news before:2026-09-05", {"end_date": "2026-09-05"}),
        (
            {"start_date": "2026-01-01", "end_date": "2026-09-05"},
            "news after:2026-01-01 before:2026-09-05",
            {"start_date": "2026-01-01", "end_date": "2026-09-05"},
        ),
        (
            {"start_date": " 2026-01-01 ", "end_date": " "},
            "news after:2026-01-01",
            {"start_date": "2026-01-01"},
        ),
    ],
)
async def test_date_bounds_reach_providers_and_results(
    monkeypatch, dates, expected_query, expected_bounds, fallback
) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    requests = []

    def behavior(params):
        requests.append(dict(params))
        if fallback and len(requests) == 1:
            raise RuntimeError("provider unavailable")
        return {"results": [{"title": "Report", "url": "https://example.com"}], "total": 1}

    tool = _tool(
        [_FakeProvider(name, behavior=behavior) for name in ("brave", "tavily")],
        default="brave",
    )
    result = await tool.execute({"query": "news", **dates}, _ctx())

    assert result.success is True
    assert len(requests) == (2 if fallback else 1)
    assert all(request["query"] == expected_query for request in requests)
    assert result.data["query"] == "news"
    assert result.data["executed_query"] == expected_query
    assert result.data.get("date_range_applied") == expected_bounds
    assert result.data["fallback_used"] is fallback


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dates",
    [
        {"start_date": "2026-13-01"},
        {"end_date": "2026-02-30"},
        {"start_date": "2026/01/01"},
        {"end_date": "invalid"},
        {"start_date": "2026-01-01", "end_date": "invalid"},
        {"start_date": "2026-09-05", "end_date": "2026-01-01"},
    ],
)
async def test_invalid_dates_fail_before_provider_execution(monkeypatch, dates) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())

    def unexpected_search(params):
        pytest.fail("Invalid dates must not reach the provider")

    tool = _tool([_FakeProvider("brave", behavior=unexpected_search)], default="brave")
    result = await tool.execute({"query": "news", **dates}, _ctx())

    assert result.success is False
    assert result.error_code == "INVALID_PARAMETERS"


@pytest.mark.asyncio
async def test_date_bounds_keep_cached_queries_distinct(monkeypatch) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    requests = []

    def behavior(params):
        requests.append(params["query"])
        return {"results": [{"title": params["query"], "url": "https://example.com"}], "total": 1}

    tool = _tool([_FakeProvider("brave", behavior=behavior)], default="brave")
    for dates in ({}, {"start_date": "2026-01-01"}, {"end_date": "2026-09-05"}):
        result = await tool.execute({"query": "news", **dates}, _ctx())
        cached = await tool.execute({"query": "news", **dates}, _ctx())
        assert result.success is True
        assert cached.success is True
        assert cached.data["cached"] is True
        assert cached.data["results"] == result.data["results"]
        assert cached.data.get("date_range_applied") == (dates or None)
    assert requests == ["news", "news after:2026-01-01", "news before:2026-09-05"]


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
async def test_reuses_cached_successful_search(monkeypatch) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    calls = 0

    def behavior(params):
        nonlocal calls
        calls += 1
        return {
            "results": [{"title": f"result {calls}", "url": "https://example.com"}],
            "result_count": 1,
        }

    tool = _tool([_FakeProvider("brave", behavior=behavior)], default="brave")

    first = await tool.execute({"query": "hello"}, _ctx())
    second = await tool.execute({"query": "hello"}, _ctx())

    assert first.success is True
    assert second.success is True
    assert second.data["cached"] is True
    assert second.data["results"][0]["title"] == "result 1"
    assert calls == 1


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


@pytest.mark.asyncio
async def test_brave_rate_limit_defers_shared_gate_and_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(web_search_tool, "get_config", lambda: _FakeConfig())
    limiter_events: list[tuple[str, str, float | None]] = []

    class _Limiter:
        async def wait(self, provider_name: str) -> None:
            limiter_events.append(("wait", provider_name, None))

        def defer(self, provider_name: str, retry_after_seconds: float | None) -> None:
            limiter_events.append(("defer", provider_name, retry_after_seconds))

    def rate_limited(_params):
        raise ProviderRateLimitError("slow down", retry_after_seconds=4.0)

    monkeypatch.setattr(
        web_search_tool,
        "get_web_search_rate_limiter",
        lambda: _Limiter(),
    )
    tool = _tool(
        [
            _FakeProvider("brave", behavior=rate_limited),
            _FakeProvider("tavily"),
        ],
        default="brave",
    )
    tool._get_provider_config = lambda name: ProviderConfig(api_key="configured")  # type: ignore[assignment]

    result = await tool.execute({"query": "hello"}, _ctx())

    assert result.success is True
    assert result.data["actual_provider"] == "tavily"
    assert limiter_events == [
        ("wait", "brave", None),
        ("defer", "brave", 4.0),
    ]
