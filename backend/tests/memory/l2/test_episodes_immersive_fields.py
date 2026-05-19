"""Tests for the immersive-timeline fields added to EpisodeWrite."""

from __future__ import annotations

import pytest


def test_episode_write_defaults_for_immersive_fields():
    from magi.memory.l2.episode_models import EpisodeWrite

    ep = EpisodeWrite(episode_id="ep-1", time_start=100.0, time_end=200.0)

    assert ep.slice_narrative == ""
    assert ep.slice_sensory_detail == ""
    assert ep.magi_standout is False
    assert ep.standout_score == 0.0
    assert ep.standout_reason == ""
    assert ep.representative_asset_ref == ""


def test_episode_write_accepts_immersive_fields():
    from magi.memory.l2.episode_models import EpisodeWrite

    ep = EpisodeWrite(
        episode_id="ep-2",
        time_start=100.0,
        time_end=200.0,
        slice_narrative="下午你在改 portrait rail。",
        slice_sensory_detail="窗外开始下雨。",
        magi_standout=True,
        standout_score=0.83,
        standout_reason="duration>90min;has_photos;first_entity",
        representative_asset_ref="photo-library://2026-05-17/IMG_4423.HEIC",
    )

    assert ep.slice_narrative == "下午你在改 portrait rail。"
    assert ep.magi_standout is True
    assert ep.standout_score == pytest.approx(0.83)
    assert ep.representative_asset_ref.startswith("photo-library://")


def test_episode_write_from_dict_round_trip_includes_immersive():
    from magi.memory.l2.episode_models import EpisodeWrite

    src = {
        "episode_id": "ep-3",
        "time_start": 0.0,
        "time_end": 1.0,
        "magi_standout": True,
        "standout_score": 0.5,
        "standout_reason": "first-of-its-kind",
        "slice_narrative": "x",
        "slice_sensory_detail": "y",
        "representative_asset_ref": "ref://y",
    }
    restored = EpisodeWrite.from_dict(src)
    out = restored.to_dict()
    assert out["magi_standout"] is True
    assert out["standout_score"] == 0.5
    assert out["standout_reason"] == "first-of-its-kind"
    assert out["slice_narrative"] == "x"
    assert out["slice_sensory_detail"] == "y"
    assert out["representative_asset_ref"] == "ref://y"


def test_episode_write_from_dict_handles_null_standout_score():
    """A None standout_score (e.g., from a NULL DB cell) must not crash."""
    from magi.memory.l2.episode_models import EpisodeWrite

    src = {
        "episode_id": "ep-4",
        "time_start": 0.0,
        "time_end": 1.0,
        "standout_score": None,
    }
    ep = EpisodeWrite.from_dict(src)
    assert ep.standout_score == 0.0


@pytest.mark.asyncio
async def test_store_round_trip_immersive_fields(l2_store_with_schema):
    store = l2_store_with_schema

    eid = "ep-rt-1"
    await store.create_episode(
        episode_id=eid,
        time_start=100.0,
        time_end=200.0,
        slice_narrative="周日下午你在读架构文档。",
        slice_sensory_detail="窗外光线很柔。",
        magi_standout=True,
        standout_score=0.72,
        standout_reason="duration",
        representative_asset_ref="photo-library://x/y.HEIC",
    )

    got = await store.get_episode(episode_id=eid)
    assert got["slice_narrative"] == "周日下午你在读架构文档。"
    assert got["slice_sensory_detail"] == "窗外光线很柔。"
    assert got["magi_standout"] is True
    assert got["standout_score"] == pytest.approx(0.72)
    assert got["standout_reason"] == "duration"
    assert got["representative_asset_ref"] == "photo-library://x/y.HEIC"


@pytest.mark.asyncio
async def test_update_episode_immersive_fields(l2_store_with_schema):
    store = l2_store_with_schema

    eid = "ep-rt-2"
    await store.create_episode(episode_id=eid, time_start=0.0, time_end=1.0)

    # Sanity: new episode created with defaults reads magi_standout as False
    pre = await store.get_episode(episode_id=eid)
    assert pre["magi_standout"] is False
    assert pre["standout_score"] == pytest.approx(0.0)

    ok = await store.update_episode(
        episode_id=eid,
        magi_standout=True,
        standout_score=0.9,
        slice_narrative="一个新的切片叙事。",
        representative_asset_ref="ref://abc",
    )
    assert ok is True

    got = await store.get_episode(episode_id=eid)
    assert got["magi_standout"] is True
    assert got["standout_score"] == pytest.approx(0.9)
    assert got["slice_narrative"] == "一个新的切片叙事。"
    assert got["representative_asset_ref"] == "ref://abc"
    # Codec returns empty string for NULL on immersive text fields (matches EpisodeWrite contract)
    assert got["slice_sensory_detail"] == ""
    assert got["standout_reason"] == ""
