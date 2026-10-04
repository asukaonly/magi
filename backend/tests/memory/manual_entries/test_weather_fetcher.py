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


@pytest.mark.parametrize(
    "code,category",
    [
        (0, "clear"),
        (1, "mostly_clear"),
        (2, "partly_cloudy"),
        (3, "overcast"),
        (45, "fog"),
        (61, "rain"),
        (65, "rain"),
        (71, "snow"),
        (95, "thunderstorm"),
        (9999, "unknown"),
    ],
)
def test_weather_category_maps_display_buckets_and_unknown_codes(code, category):
    assert weather_category(code) == category


# ─── Fetch happy path ────────────────────────────────────────────────


def _clean_hour_past(hours_ago: int) -> float:
    """A timestamp exactly N hours ago, floored to the hour, in UTC.

    Aligning to the hour makes the 'nearest slot' selection deterministic —
    otherwise sub-hour drift in time.time() can push the closest slot to
    one of the neighbors and flake the test."""
    now_floor = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    return now_floor.timestamp() - hours_ago * 3600


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offset_seconds,expected",
    [
        (-2400, (0, 17.5)),
        (-1800, (0, 17.5)),
        (0, (2, 22.5)),
        (1740, (2, 22.5)),
        (1860, (0, 27.5)),
        (10800, (0, 27.5)),
        (10801, None),
    ],
)
async def test_fetch_selects_nearest_slot_with_tie_and_window_boundaries(
    monkeypatch, offset_seconds, expected
):
    center = datetime(2026, 10, 5, 10, tzinfo=timezone.utc).timestamp()
    now = center + 4 * 3600
    monkeypatch.setattr("magi.memory.manual_entries.weather_fetcher._now", lambda: now)
    client = _StubClient(_StubResponse(_payload_for_hour(center, code=2, temp_c=22.5)))
    result = await WeatherFetcher(client_factory=lambda: client).fetch(
        lat=30.27, lng=120.15, event_at=center + offset_seconds
    )
    assert client.calls == 1
    if expected is None:
        assert result is None
    else:
        assert result == {"code": expected[0], "temp_c": expected[1], "fetched_at": now}


# ─── Caching ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lat,lng,hours,miss",
    [
        (30.21, 120.11, 0, False),
        (30.24, 120.14, 0, False),
        (30.41, 120.11, 0, True),
        (30.21, 120.41, 0, True),
        (30.21, 120.11, 1, True),
    ],
)
async def test_weather_cache_partitions_each_location_axis_and_hour(
    monkeypatch, lat, lng, hours, miss
):
    event_at = datetime(2026, 10, 5, 10, tzinfo=timezone.utc).timestamp()
    now = event_at + 4 * 3600
    monkeypatch.setattr("magi.memory.manual_entries.weather_fetcher._now", lambda: now)
    client = _StubClient(_StubResponse(_payload_for_hour(event_at, code=3, temp_c=18.0)))
    fetcher = WeatherFetcher(client_factory=lambda: client)
    first = await fetcher.fetch(lat=30.21, lng=120.11, event_at=event_at)
    assert first == {"code": 3, "temp_c": 18.0, "fetched_at": now}
    second_time = event_at + hours * 3600 + 60
    client.response = _StubResponse(_payload_for_hour(second_time, code=61, temp_c=27.0))
    second = await fetcher.fetch(lat=lat, lng=lng, event_at=second_time)
    assert second == ({"code": 61, "temp_c": 27.0, "fetched_at": now} if miss else first)
    assert client.calls == (2 if miss else 1)


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
@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": "shape"},
        [],
        {"hourly": None},
        {"hourly": {"time": "not-a-list", "temperature_2m": [20], "weather_code": [0]}},
        {"hourly": {"time": ["2026-10-05T10:00"], "temperature_2m": [], "weather_code": [0]}},
        {"hourly": {"time": ["not-a-date"], "temperature_2m": [20], "weather_code": [0]}},
        {
            "hourly": {
                "time": ["2026-10-05T10:00"],
                "temperature_2m": ["unknown"],
                "weather_code": [0],
            }
        },
    ],
)
async def test_malformed_weather_responses_return_no_observation(monkeypatch, payload):
    event_at = datetime(2026, 10, 5, 10, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr("magi.memory.manual_entries.weather_fetcher._now", lambda: event_at)
    client = _StubClient(_StubResponse(payload))
    result = await WeatherFetcher(client_factory=lambda: client).fetch(
        lat=30.27, lng=120.15, event_at=event_at
    )
    assert result is None
    assert client.calls == 1


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
