"""Tests for shared web-search provider pacing and retry metadata."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.http_errors import (
    ProviderRateLimitError,
    parse_retry_after_seconds,
)
from magi.tools.providers.web_search.brave import BraveSearchProvider
from magi.tools.providers.web_search.duckduckgo import DuckDuckGoSearchProvider
from magi.tools.providers.web_search.perplexity import PerplexitySearchProvider
from magi.tools.providers.web_search.searxng import SearXNGSearchProvider
from magi.tools.providers.web_search.tavily import TavilySearchProvider
from magi.tools.providers.web_search.rate_limit import SharedProviderRateLimiter


@pytest.mark.asyncio
async def test_limiter_reserves_shared_provider_slots() -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    limiter = SharedProviderRateLimiter(
        {"brave": 1.0},
        clock=lambda: 10.0,
        sleep=record_sleep,
    )

    await asyncio.gather(
        limiter.wait("brave"),
        limiter.wait("brave"),
        limiter.wait("brave"),
    )

    assert sorted(delays) == [1.0, 2.0]


@pytest.mark.asyncio
async def test_limiter_honors_provider_retry_after() -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    limiter = SharedProviderRateLimiter(
        {"brave": 1.0},
        clock=lambda: 10.0,
        sleep=record_sleep,
    )
    await limiter.wait("brave")
    limiter.defer("brave", 5.0)

    await limiter.wait("brave")

    assert delays == [5.0]


def test_parse_retry_after_supports_seconds_and_http_dates() -> None:
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)

    assert parse_retry_after_seconds("2.5", now=now) == 2.5
    assert parse_retry_after_seconds("Fri, 21 Aug 2026 12:00:07 GMT", now=now) == 7.0
    assert parse_retry_after_seconds("invalid", now=now) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_class,challenge", [
    (BraveSearchProvider, False), (DuckDuckGoSearchProvider, False),
    (PerplexitySearchProvider, False), (SearXNGSearchProvider, False),
    (TavilySearchProvider, False), (DuckDuckGoSearchProvider, True),
])
async def test_search_provider_distinguishes_rate_limit_from_challenge(
    monkeypatch, provider_class, challenge: bool,
) -> None:
    class _Response:
        status = 429
        headers = {"Retry-After": "6"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def text(self) -> str:
            return "Bots use DuckDuckGo too" if challenge else "Too many requests"

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        def get(self, *args, **kwargs):
            return _Response()

        post = get

    monkeypatch.setattr(
        "magi.tools.providers.web_search.brave.aiohttp.ClientSession",
        lambda **kwargs: _Session(),
    )

    with pytest.raises(Exception if challenge else ProviderRateLimitError) as captured:
        await provider_class().execute(
            {"query": "hello"},
            ProviderConfig(api_key="configured", base_url="https://example.org"),
        )

    if challenge:
        assert not isinstance(captured.value, ProviderRateLimitError)
        assert "challenge triggered" in str(captured.value)
    else:
        assert captured.value.retry_after_seconds == 6.0
