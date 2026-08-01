"""WeatherFetcher: parsing, caching, failure swallowing.

We don't hit Open-Meteo for real — a stub httpx client gives us
deterministic payloads. The fetcher should:

  1. Pick the hourly entry closest to event_at and return
     {code, temp_c, fetched_at}.
  2. Cache by (lat_grid, lng_grid, hour_bucket) so a second call with
     the same key doesn't re-fetch.
  3. Return None on network exception / malformed payload /
     out-of-window event_at — never raise.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import pytest

from magi.memory.manual_entries.weather_fetcher import (
    WMO_CATEGORY,
    PAST_DAYS_SUPPORTED,
    WeatherFetcher,
    weather_category,
)


# ─── Helpers ─────────────────────────────────────────────────────────


class _StubResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


class _StubClient:
    """Drop-in for httpx.AsyncClient with controllable response + call counter."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls = 0

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def get(self, _url: str, *, params: dict | None = None) -> Any:  # noqa: ARG002
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _payload_for_hour(event_at: float, *, code: int, temp_c: float) -> dict:
    """Build an hourly response with three slots centered on event_at."""
    dt = datetime.fromtimestamp(event_at, tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    times = []
    temps = []
    codes = []
    for offset_hours in (-1, 0, 1):
        ts = dt.timestamp() + offset_hours * 3600
        times.append(datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M"))
        # Distinct temps/codes per slot so we can verify the *middle* one is chosen.
        temps.append(temp_c if offset_hours == 0 else temp_c + offset_hours * 5)
        codes.append(code if offset_hours == 0 else 0)
    return {
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "weather_code": codes,
        },
    }


# ─── Pure helpers ────────────────────────────────────────────────────


def test_weather_category_known_codes():
    assert weather_category(0) == "clear"
    assert weather_category(2) == "partly_cloudy"
    assert weather_category(65) == "rain"
    assert weather_category(95) == "thunderstorm"


def test_weather_category_unknown_falls_back():
    assert weather_category(9999) == "unknown"


def test_wmo_table_has_expected_buckets():
    # Sanity guard against accidental code removals.
    for code in (0, 1, 2, 3, 45, 61, 71, 95):
        assert code in WMO_CATEGORY


# ─── Fetch happy path ────────────────────────────────────────────────


def _clean_hour_past(hours_ago: int) -> float:
    """A timestamp exactly N hours ago, floored to the hour, in UTC.

    Aligning to the hour makes the 'nearest slot' selection deterministic —
    otherwise sub-hour drift in time.time() can push the closest slot to
    one of the neighbors and flake the test."""
    now_floor = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    return now_floor.timestamp() - hours_ago * 3600


@pytest.mark.asyncio
async def test_fetch_picks_nearest_hour():
    event_at = _clean_hour_past(2)
    client = _StubClient(_StubResponse(_payload_for_hour(event_at, code=2, temp_c=22.5)))
    fetcher = WeatherFetcher(client_factory=lambda: client)

    result = await fetcher.fetch(lat=30.27, lng=120.15, event_at=event_at)
    assert result is not None
    assert result["code"] == 2
    assert result["temp_c"] == pytest.approx(22.5)
    assert result["fetched_at"] > 0


# ─── Caching ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_caches_by_grid_and_hour():
    event_at = _clean_hour_past(1)
    client = _StubClient(_StubResponse(_payload_for_hour(event_at, code=3, temp_c=18.0)))
    fetcher = WeatherFetcher(client_factory=lambda: client)

    # Same lat/lng/hour → second call must hit cache, not network.
    await fetcher.fetch(lat=30.27, lng=120.15, event_at=event_at)
    await fetcher.fetch(lat=30.27, lng=120.15, event_at=event_at)
    assert client.calls == 1

    # Same hour but ~50km away (different 0.1° grid) → cache miss.
    await fetcher.fetch(lat=30.78, lng=120.15, event_at=event_at)
    assert client.calls == 2


@pytest.mark.asyncio
async def test_clear_drops_cached_locations():
    event_at = _clean_hour_past(1)
    client = _StubClient(_StubResponse(_payload_for_hour(event_at, code=3, temp_c=18.0)))
    fetcher = WeatherFetcher(client_factory=lambda: client)

    await fetcher.fetch(lat=30.27, lng=120.15, event_at=event_at)
    assert await fetcher.clear() == 1
    await fetcher.fetch(lat=30.27, lng=120.15, event_at=event_at)

    assert client.calls == 2


@pytest.mark.asyncio
async def test_clear_prevents_inflight_fetch_from_repopulating_cache():
    event_at = _clean_hour_past(1)
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingClient(_StubClient):
        async def get(self, url, params):
            self.calls += 1
            started.set()
            await release.wait()
            return self.response

    client = _BlockingClient(
        _StubResponse(_payload_for_hour(event_at, code=3, temp_c=18.0))
    )
    fetcher = WeatherFetcher(client_factory=lambda: client)
    task = asyncio.create_task(
        fetcher.fetch(lat=30.27, lng=120.15, event_at=event_at)
    )
    await started.wait()

    assert await fetcher.clear() == 0
    release.set()
    assert await task is not None
    await fetcher.fetch(lat=30.27, lng=120.15, event_at=event_at)

    assert client.calls == 2


# ─── Failure modes ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_returns_none_on_network_exception():
    client = _StubClient(RuntimeError("connection refused"))
    fetcher = WeatherFetcher(client_factory=lambda: client)
    result = await fetcher.fetch(lat=30.27, lng=120.15, event_at=time.time())
    assert result is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_malformed_payload():
    # Missing 'hourly' key.
    client = _StubClient(_StubResponse({"unexpected": "shape"}))
    fetcher = WeatherFetcher(client_factory=lambda: client)
    result = await fetcher.fetch(lat=30.27, lng=120.15, event_at=time.time())
    assert result is None


@pytest.mark.asyncio
async def test_fetch_skips_event_too_far_in_past():
    """Older than PAST_DAYS_SUPPORTED → skip the API entirely."""
    very_old = time.time() - (PAST_DAYS_SUPPORTED + 5) * 86400
    client = _StubClient(_StubResponse(_payload_for_hour(very_old, code=0, temp_c=10.0)))
    fetcher = WeatherFetcher(client_factory=lambda: client)
    result = await fetcher.fetch(lat=30.27, lng=120.15, event_at=very_old)
    assert result is None
    assert client.calls == 0  # never reached out


@pytest.mark.asyncio
async def test_fetch_returns_none_when_event_outside_hourly_window():
    """API responds but the requested hour isn't in the returned slots."""
    real_event_at = time.time() - 3600
    # Build a payload whose slots are nowhere near event_at:
    far_away = real_event_at - 30 * 3600  # 30 hours earlier
    payload = _payload_for_hour(far_away, code=2, temp_c=22.0)
    client = _StubClient(_StubResponse(payload))
    fetcher = WeatherFetcher(client_factory=lambda: client)
    result = await fetcher.fetch(lat=30.27, lng=120.15, event_at=real_event_at)
    assert result is None
