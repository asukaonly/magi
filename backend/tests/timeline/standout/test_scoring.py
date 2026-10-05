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


@pytest.mark.parametrize(
    ("duration", "photos", "shifts", "entities", "score", "reason", "standout"),
    [
        (60, False, 2, [], 0.20, "state_shift[2]", False),
        (60, True, 1, [], 0.50, "photos;state_shift[1]", True),
        (60, False, 0, ["x", "y"], 0.45, "first_entity[x,y]", False),
        (7200, False, 1, [], 0.55, "duration[120min];state_shift[1]", True),
        (7200, True, 1, ["x"], 1.0, "duration[120min];photos;state_shift[1];first_entity[x]", True),
    ],
)
def test_standout_scores_preserve_contributors_cap_and_inclusive_threshold(
    duration, photos, shifts, entities, score, reason, standout
):
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    actual_score, actual_reason, actual_standout = compute_standout_score(
        episode={"time_start": 0.0, "time_end": duration},
        signals=StandoutSignals(
            has_photos=photos, state_shift_count=shifts, first_seen_entities=entities
        ),
    )
    assert actual_score == pytest.approx(score)
    assert actual_reason == reason
    assert actual_standout is standout
