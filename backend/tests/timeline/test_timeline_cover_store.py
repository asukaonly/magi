from __future__ import annotations

from pathlib import Path

import pytest

from magi.timeline.cover_store import TimelineCoverPreferenceStore


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode, asset_ref, source",
    [("asset", "photo-library://asset-a", "current_period"), ("hidden", None, "current_period")],
)
async def test_cover_preference_survives_reopen_and_clears_only_its_window(
    tmp_path: Path, mode, asset_ref, source
):
    db_path = str(tmp_path / "memory.db")
    store = TimelineCoverPreferenceStore(db_path=db_path)
    control = await store.set_preference(
        scale="day", period_start=200.0, period_end=300.0, mode="hidden"
    )
    saved = await store.set_preference(
        scale="day",
        period_start=100.0,
        period_end=200.0,
        mode=mode,
        asset_ref=asset_ref,
        source=source,
    )
    reopened = TimelineCoverPreferenceStore(db_path=db_path)
    loaded = await reopened.get_preference(scale="day", period_start=100.0, period_end=200.0)
    assert saved == loaded
    assert loaded["mode"] == mode
    assert loaded["asset_ref"] == asset_ref
    assert loaded["source"] == ("hidden" if mode == "hidden" else source)
    assert (
        await reopened.clear_preference(scale="day", period_start=100.0, period_end=200.0) is True
    )
    assert await reopened.get_preference(scale="day", period_start=100.0, period_end=200.0) is None
    assert (
        await reopened.clear_preference(scale="day", period_start=100.0, period_end=200.0) is False
    )
    assert (
        await reopened.get_preference(scale="day", period_start=200.0, period_end=300.0) == control
    )


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
