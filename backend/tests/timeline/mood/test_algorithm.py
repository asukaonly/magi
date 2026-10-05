"""Tests for the daily mood aggregate algorithm (Algorithm C)."""

from __future__ import annotations

import pytest


def test_flat_warm_day_has_low_volatility():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    # 24 samples of valence 0.5 (warm) at hourly intervals
    samples = [(float(h * 3600), 0.5) for h in range(24)]
    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=samples)

    assert agg.day_local_date == "2026-05-17"
    assert agg.dominant_valence == "warm"
    assert agg.volatility_score < 0.1
    assert agg.event_count == 24
    assert len(agg.state_curve_compact) == 24


def test_mixed_morning_tense_afternoon_bright_has_high_volatility():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    # First half tense (-0.6), second half bright (0.75)
    samples = [(float(h * 3600), -0.6) for h in range(12)]
    samples += [(float(h * 3600), 0.75) for h in range(12, 24)]
    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=samples)

    assert agg.volatility_score > 0.5
    assert agg.dominant_valence in ("tense", "bright")
    assert len(agg.state_curve_compact) == 24


def test_dominant_valence_is_longest_band_by_time():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    # Three short tense observations lose to one long warm interval.
    samples = [(0.0, -0.8), (10.0, -0.8), (20.0, -0.8), (30.0, 0.5), (3600.0, 0.0)]
    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=samples)

    assert agg.dominant_valence == "warm"


def test_empty_samples_produces_neutral_default():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=[])
    assert agg.dominant_valence == "neutral"
    assert agg.volatility_score == pytest.approx(0.0)
    assert agg.event_count == 0
    assert agg.state_curve_compact == []


@pytest.mark.parametrize(
    "cutoff, below, at_or_above",
    [
        (0.6, "warm", "bright"),
        (0.2, "neutral", "warm"),
        (-0.2, "cool", "neutral"),
        (-0.5, "tense", "cool"),
    ],
)
def test_valence_band_cutoffs(cutoff, below, at_or_above):
    from math import inf, nextafter
    from magi.timeline.mood.algorithm import valence_to_band

    assert valence_to_band(nextafter(cutoff, -inf)) == below
    assert valence_to_band(cutoff) == at_or_above
    assert valence_to_band(nextafter(cutoff, inf)) == at_or_above
