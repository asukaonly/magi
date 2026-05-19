"""Tests for the standout scoring heuristic."""

from __future__ import annotations

import pytest


def test_short_episode_with_no_signals_scores_low():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 100.0, "time_end": 200.0, "primary_entity_ids": []}
    signals = StandoutSignals(has_photos=False, state_shift_count=0, first_seen_entities=[])

    score, reason, is_standout = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.0)
    assert is_standout is False
    assert "no signals" in reason or reason == ""


def test_long_episode_with_photos_scores_higher():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    # Duration: 2 hours (> 90 min threshold)
    episode = {"time_start": 0.0, "time_end": 7200.0, "primary_entity_ids": []}
    signals = StandoutSignals(has_photos=True, state_shift_count=0, first_seen_entities=[])

    score, reason, is_standout = compute_standout_score(episode=episode, signals=signals)
    # 0.35 (duration) + 0.30 (photos) = 0.65
    assert score == pytest.approx(0.65)
    assert is_standout is True
    assert "duration" in reason
    assert "photos" in reason


def test_first_entity_appearance_caps_at_0_45():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 0.0, "time_end": 60.0, "primary_entity_ids": ["x", "y", "z"]}
    signals = StandoutSignals(
        has_photos=False,
        state_shift_count=0,
        first_seen_entities=["x", "y", "z"],  # 3 firsts * 0.30 = 0.90, but capped at 0.45
    )

    score, _, _ = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.45)


def test_state_shift_signal_adds_0_20():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 0.0, "time_end": 60.0, "primary_entity_ids": []}
    signals = StandoutSignals(has_photos=False, state_shift_count=2, first_seen_entities=[])

    score, _, _ = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.20)


def test_threshold_promotes_to_magi_standout_at_0_50():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    # Duration + state_shift = 0.35 + 0.20 = 0.55, above 0.50 threshold
    episode = {"time_start": 0.0, "time_end": 7200.0}
    signals = StandoutSignals(has_photos=False, state_shift_count=1, first_seen_entities=[])

    score, _, is_standout = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.55)
    assert is_standout is True


def test_reason_includes_all_contributing_signals():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 0.0, "time_end": 7200.0, "primary_entity_ids": ["x"]}
    signals = StandoutSignals(has_photos=True, state_shift_count=1, first_seen_entities=["x"])

    _, reason, _ = compute_standout_score(episode=episode, signals=signals)
    # Reason is a ;-joined list of signals
    assert "duration" in reason
    assert "photos" in reason
    assert "first_entity" in reason
    assert "state_shift" in reason
