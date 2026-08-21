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
async def test_brave_provider_exposes_retry_after(monkeypatch) -> None:
    class _Response:
        status = 429
        headers = {"Retry-After": "6"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        def get(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(
        "magi.tools.providers.web_search.brave.aiohttp.ClientSession",
        lambda **kwargs: _Session(),
    )

    with pytest.raises(ProviderRateLimitError) as captured:
        await BraveSearchProvider().execute(
            {"query": "hello"},
            ProviderConfig(api_key="configured"),
        )

    assert captured.value.retry_after_seconds == 6.0
