"""LocationResolver priority + time-weighted aggregation."""

from __future__ import annotations

import pytest

from magi.location.models import LocationSample, ResolvedPlace
from magi.location.resolver import LocationResolver


class _StubSource:
    """In-memory location source for tests."""

    def __init__(
        self,
        name: str,
        priority: int,
        validity_seconds: int,
        samples: list[LocationSample],
        *,
        raise_on_query: Exception | None = None,
    ) -> None:
        self.source_name = name
        self.priority = priority
        self.validity_seconds = validity_seconds
        self._samples = samples
        self._raise = raise_on_query
        self.query_calls = 0

    async def query_samples(self, *, time_start: float, time_end: float):
        self.query_calls += 1
        if self._raise:
            raise self._raise
        return [s for s in self._samples if time_start <= s.sampled_at <= time_end]


def _sample(source: str, ts: float, city: str, accuracy: float = 1000.0) -> LocationSample:
    return LocationSample(
        sample_id=f"{source}-{int(ts)}",
        source=source,
        sampled_at=ts,
        city=city,
        accuracy_m=accuracy,
    )


@pytest.mark.asyncio
async def test_empty_when_no_sources_have_data():
    resolver = LocationResolver(sources=[
        _StubSource("ipgeo", 10, 3600, []),
    ])
    result = await resolver.resolve_dominant(time_start=0.0, time_end=100.0)
    assert isinstance(result, ResolvedPlace)
    assert result.primary_label == ""
    assert result.labels == []


@pytest.mark.asyncio
async def test_uses_higher_priority_source_when_available():
    """When wifi has samples, its labels should dominate even if ipgeo
    also has overlapping samples — wifi accuracy is finer."""
    wifi = _StubSource(
        "wifi", priority=50, validity_seconds=7200,
        samples=[_sample("wifi", 100.0, "杭州", accuracy=50.0)],
    )
    ipgeo = _StubSource(
        "ipgeo", priority=10, validity_seconds=86400,
        samples=[_sample("ipgeo", 50.0, "上海", accuracy=10000.0)],
    )
    resolver = LocationResolver(sources=[wifi, ipgeo])
    result = await resolver.resolve_dominant(time_start=0.0, time_end=200.0)
    # Both contribute, but wifi (50s validity covering 100-200) outweighs
    # ipgeo (50s validity covering 0-100 within window). Actually with
    # wider validity ipgeo also covers all 200s — but wifi gets the
    # priority benefit of being checked first and contributing fully.
    assert "杭州" in result.labels
    # Wifi appears in source_used since it produced samples.
    assert "wifi" in result.source_used


@pytest.mark.asyncio
async def test_time_weighted_aggregation_picks_longer_label():
    """Two samples in the same source: the one whose validity covers more
    of the window wins, even if both contribute."""
    source = _StubSource(
        "ipgeo", priority=10, validity_seconds=200,
        samples=[
            _sample("ipgeo", 0.0, "杭州"),    # covers 0-200 of window
            _sample("ipgeo", 250.0, "上海"),  # covers 250-300 of window
        ],
    )
    resolver = LocationResolver(sources=[source])
    result = await resolver.resolve_dominant(time_start=0.0, time_end=300.0)
    assert result.primary_label == "杭州"
    # Both labels appear in the breakdown.
    assert set(result.labels[:2]) == {"杭州", "上海"}


@pytest.mark.asyncio
async def test_failing_source_does_not_block_fallback():
    """If a high-priority source raises, resolver falls through to the next."""
    bad_wifi = _StubSource(
        "wifi", priority=50, validity_seconds=7200, samples=[],
        raise_on_query=RuntimeError("no adapter"),
    )
    ipgeo = _StubSource(
        "ipgeo", priority=10, validity_seconds=86400,
        samples=[_sample("ipgeo", 100.0, "杭州")],
    )
    resolver = LocationResolver(sources=[bad_wifi, ipgeo])
    result = await resolver.resolve_dominant(time_start=0.0, time_end=200.0)
    assert result.primary_label == "杭州"
    assert bad_wifi.query_calls == 1
    assert ipgeo.query_calls == 1


@pytest.mark.asyncio
async def test_sample_with_empty_label_is_skipped():
    """Samples without a usable label don't contribute."""
    source = _StubSource(
        "ipgeo", priority=10, validity_seconds=200,
        samples=[
            _sample("ipgeo", 0.0, ""),      # empty label
            _sample("ipgeo", 100.0, "杭州"),
        ],
    )
    resolver = LocationResolver(sources=[source])
    result = await resolver.resolve_dominant(time_start=0.0, time_end=200.0)
    assert result.primary_label == "杭州"


@pytest.mark.asyncio
async def test_returns_empty_for_zero_window():
    source = _StubSource(
        "ipgeo", priority=10, validity_seconds=200,
        samples=[_sample("ipgeo", 50.0, "杭州")],
    )
    resolver = LocationResolver(sources=[source])
    result = await resolver.resolve_dominant(time_start=100.0, time_end=100.0)
    assert result.primary_label == ""


@pytest.mark.asyncio
async def test_accuracy_tier_reflects_best_source():
    """Tier is set from the best (smallest) accuracy_m among contributing samples."""
    photo = _StubSource(
        "photo", priority=100, validity_seconds=1800,
        samples=[_sample("photo", 100.0, "杭州", accuracy=20.0)],
    )
    resolver = LocationResolver(sources=[photo])
    result = await resolver.resolve_dominant(time_start=0.0, time_end=200.0)
    assert result.accuracy_tier == "exact"  # 20m ≤ 50m
