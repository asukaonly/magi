"""Tests for the immersive-timeline fields added to EpisodeWrite."""

from __future__ import annotations

import pytest


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
@pytest.mark.parametrize("explicit", [False, True])
async def test_episode_immersive_fields_survive_codec_and_store(explicit, l2_store_with_schema):
    from magi.memory.l2.episode_models import EpisodeWrite

    defaults = {
        "slice_narrative": "",
        "slice_sensory_detail": "",
        "magi_standout": False,
        "standout_score": 0.0,
        "standout_reason": "",
        "representative_asset_ref": "",
    }
    supplied = {
        "slice_narrative": "周日下午你在读架构文档。",
        "slice_sensory_detail": "窗外光线很柔。",
        "magi_standout": True,
        "standout_score": 0.72,
        "standout_reason": "duration",
        "representative_asset_ref": "photo-library://x/y.HEIC",
    }
    expected = supplied if explicit else defaults
    write = EpisodeWrite.from_dict(
        {
            "episode_id": "episode-fields",
            "time_start": 100.0,
            "time_end": 200.0,
            **(supplied if explicit else {}),
        }
    )
    wire = write.to_dict()
    assert {key: wire[key] for key in defaults} == expected
    await l2_store_with_schema.create_episode(**wire)
    stored = await l2_store_with_schema.get_episode(episode_id="episode-fields")
    assert {key: stored[key] for key in defaults} == expected


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


@pytest.mark.asyncio
async def test_list_standout_episodes_returns_user_pinned_and_magi(l2_store_with_schema):
    store = l2_store_with_schema

    await store.create_episode(episode_id="ep-plain", time_start=100.0, time_end=200.0)
    await store.create_episode(episode_id="ep-pinned", time_start=300.0, time_end=400.0)
    await store.update_episode(episode_id="ep-pinned", user_pinned=True)
    await store.create_episode(
        episode_id="ep-magi", time_start=500.0, time_end=600.0,
        magi_standout=True, standout_score=0.8,
    )

    rows = await store.list_standout_episodes()
    ids = [r["episode_id"] for r in rows]
    assert "ep-plain" not in ids
    assert set(ids) == {"ep-pinned", "ep-magi"}
    # DESC by time_start
    assert rows[0]["episode_id"] == "ep-magi"


@pytest.mark.asyncio
async def test_list_standout_episodes_respects_time_window(l2_store_with_schema):
    store = l2_store_with_schema

    await store.create_episode(episode_id="ep-a", time_start=100.0, time_end=200.0)
    await store.update_episode(episode_id="ep-a", user_pinned=True)
    await store.create_episode(episode_id="ep-b", time_start=500.0, time_end=600.0)
    await store.update_episode(episode_id="ep-b", user_pinned=True)

    rows = await store.list_standout_episodes(period_start=400.0, period_end=700.0)
    assert [r["episode_id"] for r in rows] == ["ep-b"]
