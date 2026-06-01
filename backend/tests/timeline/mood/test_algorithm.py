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

    # 1 hour tense, 23 hours warm — warm should dominate
    samples = [(0.0, -0.5)] + [(float(h * 3600), 0.5) for h in range(1, 24)]
    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=samples)

    assert agg.dominant_valence == "warm"


def test_empty_samples_produces_neutral_default():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=[])
    assert agg.dominant_valence == "neutral"
    assert agg.volatility_score == pytest.approx(0.0)
    assert agg.event_count == 0
    assert agg.state_curve_compact == []


def test_valence_band_thresholds_match_spec():
    from magi.timeline.mood.algorithm import valence_to_band

    assert valence_to_band(0.65) == "bright"
    assert valence_to_band(0.45) == "warm"
    assert valence_to_band(0.0) == "neutral"
    assert valence_to_band(-0.3) == "cool"
    assert valence_to_band(-0.6) == "tense"
