from __future__ import annotations

from pathlib import Path

import pytest

from magi.timeline.cover_store import TimelineCoverPreferenceStore


@pytest.mark.asyncio
async def test_cover_store_saves_asset_preference(tmp_path: Path) -> None:
    store = TimelineCoverPreferenceStore(db_path=str(tmp_path / "memory.db"))

    saved = await store.set_preference(
        scale="day",
        period_start=100.0,
        period_end=200.0,
        mode="asset",
        asset_ref="photo-library://asset-a",
        source="current_period",
    )

    loaded = await store.get_preference(scale="day", period_start=100.0, period_end=200.0)
    assert saved == loaded
    assert loaded is not None
    assert loaded["mode"] == "asset"
    assert loaded["asset_ref"] == "photo-library://asset-a"
    assert loaded["source"] == "current_period"


@pytest.mark.asyncio
async def test_cover_store_hides_and_restores_auto(tmp_path: Path) -> None:
    store = TimelineCoverPreferenceStore(db_path=str(tmp_path / "memory.db"))

    hidden = await store.set_preference(
        scale="day",
        period_start=100.0,
        period_end=200.0,
        mode="hidden",
    )
    assert hidden["mode"] == "hidden"
    assert hidden["asset_ref"] is None

    restored = await store.clear_preference(scale="day", period_start=100.0, period_end=200.0)

    assert restored is True
    assert await store.get_preference(scale="day", period_start=100.0, period_end=200.0) is None


@pytest.mark.asyncio
async def test_cover_store_requires_asset_ref_for_asset_mode(tmp_path: Path) -> None:
    store = TimelineCoverPreferenceStore(db_path=str(tmp_path / "memory.db"))

    with pytest.raises(ValueError):
        await store.set_preference(
            scale="day",
            period_start=100.0,
            period_end=200.0,
            mode="asset",
            asset_ref="",
        )


@pytest.mark.asyncio
async def test_cover_store_rejects_unknown_asset_source(tmp_path: Path) -> None:
    store = TimelineCoverPreferenceStore(db_path=str(tmp_path / "memory.db"))

    with pytest.raises(ValueError, match="Unsupported timeline cover source"):
        await store.set_preference(
            scale="day",
            period_start=100.0,
            period_end=200.0,
            mode="asset",
            asset_ref="manual-entry-asset:///tmp/private.jpg",
            source="untrusted",  # type: ignore[arg-type]
        )
