"""LocationSampleStore + PlaceGeocodeCache CRUD."""

from __future__ import annotations

import pytest

from magi.location.models import LocationSample
from magi.location.store import LocationSampleStore, PlaceGeocodeCache


@pytest.mark.asyncio
async def test_insert_and_query_window(location_store: LocationSampleStore):
    s1 = LocationSample(sample_id="", source="ipgeo", sampled_at=100.0, city="A")
    s2 = LocationSample(sample_id="", source="ipgeo", sampled_at=200.0, city="B")
    s3 = LocationSample(sample_id="", source="wifi", sampled_at=150.0, city="C")
    for s in (s1, s2, s3):
        await location_store.insert(s)

    in_window = await location_store.query_window(time_start=120.0, time_end=180.0)
    assert [s.city for s in in_window] == ["C"]

    only_ipgeo = await location_store.query_window(
        time_start=0.0, time_end=300.0, source="ipgeo",
    )
    assert [s.city for s in only_ipgeo] == ["A", "B"]


@pytest.mark.asyncio
async def test_latest_filters_by_source_and_cutoff(location_store: LocationSampleStore):
    await location_store.insert(LocationSample(sample_id="", source="ipgeo", sampled_at=100.0, city="A"))
    await location_store.insert(LocationSample(sample_id="", source="ipgeo", sampled_at=200.0, city="B"))
    await location_store.insert(LocationSample(sample_id="", source="wifi", sampled_at=300.0, city="C"))

    latest_any = await location_store.latest()
    assert latest_any.city == "C"

    latest_ipgeo = await location_store.latest(source="ipgeo")
    assert latest_ipgeo.city == "B"

    latest_before = await location_store.latest(source="ipgeo", before=150.0)
    assert latest_before.city == "A"


@pytest.mark.asyncio
async def test_geocode_cache_roundtrip(geocode_cache: PlaceGeocodeCache):
    miss = await geocode_cache.lookup(30.27, 120.15)
    assert miss is None

    await geocode_cache.put(
        30.27, 120.15, city="杭州", region="浙江", country="China", poi_name=None,
    )
    hit = await geocode_cache.lookup(30.27, 120.15)
    assert hit is not None
    assert hit["city"] == "杭州"
    assert hit["region"] == "浙江"
    assert hit["country"] == "China"


@pytest.mark.asyncio
async def test_geocode_cache_grid_quantization(geocode_cache: PlaceGeocodeCache):
    """Coordinates within ~10m collapse to the same cache entry."""
    await geocode_cache.put(30.27001, 120.15001, city="杭州")
    hit = await geocode_cache.lookup(30.27002, 120.15001)  # same 4-dec grid
    assert hit is not None
    assert hit["city"] == "杭州"
