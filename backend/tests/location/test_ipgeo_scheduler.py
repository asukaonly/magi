"""Tests for opt-in ambient IP location polling, proxy routing, and retired WiFi cleanup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.location.nominatim import NominatimClient
from magi.location.scheduler_contrib import IPGeoPollSchedulerContrib
from magi.location.sources.ipgeo import IPGeoLocationSource
from magi.memory.manual_entries.weather_fetcher import WeatherFetcher
from magi.scheduler.contracts import ScheduledExecutionContext, ScheduledTargetType
from magi.scheduler.repository import ScheduleRepository


def _ctx(triggered_at: float = 1000.0) -> ScheduledExecutionContext:
    return ScheduledExecutionContext(
        schedule=MagicMock(),
        target_state=MagicMock(),
        runtime_dir=None,
        triggered_at=triggered_at,
        manual=False,
    )


@pytest.mark.asyncio
async def test_ipgeo_scheduler_skips_when_disabled_by_default():
    source = MagicMock()
    source.poll_and_persist = AsyncMock()
    contrib = IPGeoPollSchedulerContrib(ipgeo_source=source)

    result = await contrib._handle_poll(_ctx())

    assert result.success is True
    assert result.stats.get("skipped") == "disabled"
    source.poll_and_persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_ipgeo_scheduler_polls_when_explicitly_enabled():
    sample = MagicMock()
    sample.city = "Hangzhou"
    sample.region = "Zhejiang"
    sample.country = "China"
    source = MagicMock()
    source.poll_and_persist = AsyncMock(return_value=sample)
    contrib = IPGeoPollSchedulerContrib(ipgeo_source=source, is_enabled=lambda: True)

    result = await contrib._handle_poll(_ctx())

    assert result.success is True
    assert result.stats["city"] == "Hangzhou"
    source.poll_and_persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_ipgeo_source_passes_proxy_and_trust_env_false(monkeypatch, location_store):
    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "city": "Tokyo",
                "region": "Tokyo",
                "country_name": "Japan",
                "latitude": 35.68,
                "longitude": 139.76,
            }

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return _FakeResponse()

    monkeypatch.setattr("magi.location.sources.ipgeo.httpx.AsyncClient", _FakeAsyncClient)
    source = IPGeoLocationSource(
        store=location_store,
        proxy_url_resolver=lambda: "http://127.0.0.1:7890",
    )

    sample = await source.poll_and_persist()

    assert sample is not None
    assert sample.city == "Tokyo"
    assert captured["proxy"] == "http://127.0.0.1:7890"
    assert captured["trust_env"] is False


@pytest.mark.asyncio
async def test_nominatim_client_passes_proxy_and_trust_env_false(monkeypatch, geocode_cache):
    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "address": {"city": "Kyoto", "state": "Kyoto", "country": "Japan"},
            }

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, params=None):
            return _FakeResponse()

    monkeypatch.setattr("magi.location.nominatim.httpx.AsyncClient", _FakeAsyncClient)
    client = NominatimClient(
        cache=geocode_cache,
        proxy_url_resolver=lambda: "socks5://127.0.0.1:1080",
    )

    labels = await client.reverse(35.01, 135.76)

    assert labels is not None
    assert labels["city"] == "Kyoto"
    assert captured["proxy"] == "socks5://127.0.0.1:1080"
    assert captured["trust_env"] is False


@pytest.mark.asyncio
async def test_weather_fetcher_default_client_uses_proxy_and_trust_env_false(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "hourly": {
                    "time": ["2026-10-05T10:00"],
                    "temperature_2m": [21.5],
                    "weather_code": [0],
                }
            }

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, params=None):
            return _FakeResponse()

    event_at = 1791194400.0  # 2026-10-05T10:00:00Z
    monkeypatch.setattr("magi.memory.manual_entries.weather_fetcher._now", lambda: event_at)
    monkeypatch.setattr("magi.memory.manual_entries.weather_fetcher.httpx.AsyncClient", _FakeAsyncClient)

    fetcher = WeatherFetcher(proxy_url_resolver=lambda: "http://127.0.0.1:7890")
    weather = await fetcher.fetch(lat=30.0, lng=120.0, event_at=event_at)

    assert weather is not None
    assert weather["code"] == 0
    assert captured["proxy"] == "http://127.0.0.1:7890"
    assert captured["trust_env"] is False


@pytest.mark.asyncio
async def test_scheduler_repository_prunes_retired_wifi_schedule(tmp_path):
    from magi.db.runner import run_upgrade_database

    db_path = tmp_path / "scheduler.db"
    run_upgrade_database("scheduler", db_path)
    repo = ScheduleRepository(db_path)

    async with repo._connect() as db:
        await db.execute(
            """
            INSERT INTO schedules (
                schedule_id, target_type, target_key, trigger_type, trigger_config,
                target_payload, metadata, enabled, job_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "location_wifi_poll",
                "location_wifi_poll",
                "location_wifi_poll",
                "interval",
                '{"seconds": 600}',
                "{}",
                "{}",
                1,
                "location_wifi_poll",
                1.0,
                1.0,
            ),
        )
        await db.execute(
            """
            INSERT INTO target_state (
                target_type, target_key, running, stats_json, updated_at
            ) VALUES (?, ?, 0, '{}', 1.0)
            """,
            ("location_wifi_poll", "location_wifi_poll"),
        )
        await db.commit()

    await repo.initialize()

    assert not hasattr(ScheduledTargetType, "LOCATION_WIFI_POLL")
    schedules = await repo.list_schedules()
    assert schedules == []
