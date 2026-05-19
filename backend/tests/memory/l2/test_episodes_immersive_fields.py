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
