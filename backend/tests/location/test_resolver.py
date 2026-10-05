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
@pytest.mark.parametrize("ip_time,expected", [(50.0, ["上海", "杭州"]), (100.0, ["杭州", "上海"])])
async def test_duration_selects_dominant_label_and_priority_breaks_equal_coverage(
    ip_time, expected
):
    wifi = _StubSource("wifi", 50, 7200, [_sample("wifi", 100.0, "杭州", 50.0)])
    ipgeo = _StubSource("ipgeo", 10, 86400, [_sample("ipgeo", ip_time, "上海", 10000.0)])
    for sources in ([wifi, ipgeo], [ipgeo, wifi]):
        result = await LocationResolver(sources=sources).resolve_dominant(
            time_start=0, time_end=200
        )
        assert result.primary_label == expected[0]
        assert result.labels == expected
        assert set(result.source_used.split(",")) == {"wifi", "ipgeo"}


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_sample", [False, True])
async def test_time_weighting_ignores_unlabeled_samples(empty_sample):
    """Two samples in the same source: the one whose validity covers more
    of the window wins, even if both contribute."""
    source = _StubSource(
        "ipgeo",
        priority=10,
        validity_seconds=200,
        samples=[
            _sample("ipgeo", 0.0, "杭州"),  # covers 0-200 of window
            _sample("ipgeo", 250.0, "上海"),  # covers 250-300 of window
        ],
    )
    if empty_sample:
        source._samples.append(_sample("ipgeo", 290.0, ""))
    resolver = LocationResolver(sources=[source])
    result = await resolver.resolve_dominant(time_start=0.0, time_end=300.0)
    assert result.primary_label == "杭州"
    # Both labels appear in the breakdown.
    assert result.labels == ["杭州", "上海"]


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
async def test_returns_empty_for_zero_window():
    source = _StubSource(
        "ipgeo",
        priority=10,
        validity_seconds=200,
        samples=[_sample("ipgeo", 100.0, "杭州")],
    )
    resolver = LocationResolver(sources=[source])
    result = await resolver.resolve_dominant(time_start=100.0, time_end=100.0)
    assert result.primary_label == ""

    assert source.query_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "accuracy,tier",
    [(50.0, "exact"), (50.001, "neighborhood"), (1500.0, "neighborhood"), (1500.001, "city")],
)
async def test_best_contributing_accuracy_controls_tier_at_thresholds(accuracy, tier):
    coarse = _StubSource("coarse", 100, 1800, [_sample("coarse", 0, "杭州", 10000.0)])
    precise = _StubSource("precise", 10, 1800, [_sample("precise", 100, "杭州", accuracy)])
    result = await LocationResolver(sources=[coarse, precise]).resolve_dominant(
        time_start=0, time_end=200
    )
    assert result.accuracy_tier == tier
    assert result.primary_label == "杭州"
    assert set(result.source_used.split(",")) == {"coarse", "precise"}
