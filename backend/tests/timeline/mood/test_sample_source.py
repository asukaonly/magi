"""Tests for L2ValenceSampleSource."""

from __future__ import annotations

import pytest


class _FakeL2Store:
    def __init__(self, assertions: list[dict]) -> None:
        self._assertions = assertions
        self.last_call: dict | None = None

    async def list_tom_assertions(self, **kwargs) -> list[dict]:
        self.last_call = kwargs
        return self._assertions


@pytest.mark.asyncio
async def test_returns_empty_when_no_assertions():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    src = L2ValenceSampleSource(l2_store=_FakeL2Store([]))
    out = await src.list_valence_samples(start=0.0, end=1000.0)
    assert out == []


@pytest.mark.asyncio
async def test_maps_assertions_to_timestamp_valence_pairs():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource, ValenceSample

    assertions = [
        {
            "observed_at": 100.0,
            "trait_value": "0.5",
            "evidence_events": ["event-one"],
        },
        {
            "observed_at": 200.0,
            "trait_value": -0.3,
            "evidence_events": ["event-two", "event-shared"],
        },
        {
            "created_at": 300.0,
            "trait_value": 0.0,
            "evidence_events": ["event-three"],
        },  # falls back to created_at
    ]
    src = L2ValenceSampleSource(l2_store=_FakeL2Store(assertions))
    out = await src.list_valence_samples(start=0.0, end=500.0)
    out_sorted = sorted(out, key=lambda sample: sample.timestamp)
    assert out_sorted == [
        ValenceSample(100.0, 0.5, ("event-one",)),
        ValenceSample(200.0, -0.3, ("event-two", "event-shared")),
        ValenceSample(300.0, 0.0, ("event-three",)),
    ]


@pytest.mark.asyncio
async def test_clamps_valence_to_range():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    assertions = [
        {"observed_at": 100.0, "trait_value": 2.5, "evidence_events": ["event-one"]},
        {"observed_at": 200.0, "trait_value": -5.0, "evidence_events": ["event-two"]},
    ]
    src = L2ValenceSampleSource(l2_store=_FakeL2Store(assertions))
    out = await src.list_valence_samples(start=0.0, end=500.0)
    values = sorted(sample.valence for sample in out)
    assert values == [-1.0, 1.0]


@pytest.mark.asyncio
async def test_skips_assertions_with_unparseable_trait_value():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    assertions = [
        {
            "observed_at": 100.0,
            "trait_value": "calm",
            "evidence_events": ["event-one"],
        },
        {
            "observed_at": 200.0,
            "trait_value": 0.5,
            "evidence_events": ["event-two"],
        },
    ]
    src = L2ValenceSampleSource(l2_store=_FakeL2Store(assertions))
    out = await src.list_valence_samples(start=0.0, end=500.0)
    assert len(out) == 1
    assert out[0].timestamp == 200.0
    assert out[0].valence == 0.5
    assert out[0].source_event_ids == ("event-two",)


@pytest.mark.asyncio
async def test_skips_assertions_without_source_lineage():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    src = L2ValenceSampleSource(l2_store=_FakeL2Store([{"observed_at": 100.0, "trait_value": 0.5}]))

    assert await src.list_valence_samples(start=0.0, end=500.0) == []


@pytest.mark.asyncio
async def test_passes_window_via_temporal_clause():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    store = _FakeL2Store([])
    src = L2ValenceSampleSource(l2_store=store)
    await src.list_valence_samples(start=100.0, end=200.0)

    assert store.last_call is not None
    assert "mood" in store.last_call.get("trait_families", [])

    clause = store.last_call.get("temporal_clause")
    assert clause is not None
    sql, params = clause
    assert "observed_at" in sql
    assert params == [100.0, 200.0]


@pytest.mark.asyncio
async def test_swallows_l2_store_errors_returns_empty():
    """If the L2 store raises, the source returns [] rather than propagating."""
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    class _ErroringL2:
        async def list_tom_assertions(self, **kwargs):
            raise RuntimeError("L2 dead")

    src = L2ValenceSampleSource(l2_store=_ErroringL2())
    out = await src.list_valence_samples(start=0.0, end=500.0)
    assert out == []
