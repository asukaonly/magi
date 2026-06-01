"""Fixtures for the location subsystem tests."""

from __future__ import annotations

import pytest
import pytest_asyncio

from magi.location.store import LocationSampleStore, PlaceGeocodeCache

from _shared.memory_schema import apply_memory_shared_schema


@pytest_asyncio.fixture
async def location_store(tmp_path) -> LocationSampleStore:
    db_path = str(tmp_path / "loc.db")
    await apply_memory_shared_schema(db_path)
    return LocationSampleStore(db_path=db_path)


@pytest_asyncio.fixture
async def geocode_cache(tmp_path) -> PlaceGeocodeCache:
    db_path = str(tmp_path / "cache.db")
    await apply_memory_shared_schema(db_path)
    return PlaceGeocodeCache(db_path=db_path)
