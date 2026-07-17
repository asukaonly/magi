"""Algorithm C: time-weighted dominant valence + volatility + sparkline.

The dominant_valence is the band that held the longest time fraction of
the day. The volatility_score is a scaled standard deviation of valence
samples. The state_curve_compact is an hourly-bucketed valence list
(one float per hour that has any samples).
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from typing import Iterable, Sequence

from ...memory.l3.daily_mood.models import DailyMoodAggregate


VALENCE_BANDS: Sequence[tuple[float, str]] = (
    (0.60, "bright"),
    (0.20, "warm"),
    (-0.20, "neutral"),
    (-0.50, "cool"),
    (-1.01, "tense"),  # catch-all floor
)


def valence_to_band(valence: float) -> str:
    """Map a valence value [-1, 1] to a band label."""
    for threshold, band in VALENCE_BANDS:
        if valence >= threshold:
            return band
    return "tense"


def compute_daily_mood_aggregate(
    *,
    day_local_date: str,
    samples: Iterable[tuple[float, float]],
    source_event_ids: Iterable[str] = (),
) -> DailyMoodAggregate:
    """Compute the per-day aggregate from raw (timestamp, valence) samples.

    The samples should span a single day, with timestamps relative to the
    day start (0 to ~86400 seconds). Caller is responsible for bucketing
    per-day before invoking.
    """
    samples_list = sorted(samples, key=lambda s: s[0])
    normalized_source_event_ids = list(
        dict.fromkeys(
            str(event_id).strip()
            for event_id in source_event_ids
            if str(event_id).strip()
        )
    )

    if not samples_list:
        return DailyMoodAggregate(
            day_local_date=day_local_date,
            dominant_valence="neutral",
            volatility_score=0.0,
            state_curve_compact=[],
            event_count=0,
            source_event_ids=[],
            computed_at=time.time(),
        )

    # Time-weighted dominant band: each sample carries a duration weight
    # equal to its gap from the next sample (last sample gets a small
    # default residual).
    band_durations: Counter[str] = Counter()
    for i, (ts, val) in enumerate(samples_list):
        band = valence_to_band(val)
        if i < len(samples_list) - 1:
            duration = samples_list[i + 1][0] - ts
        else:
            duration = 60.0
        if duration <= 0:
            duration = 60.0
        band_durations[band] += duration

    dominant_valence = band_durations.most_common(1)[0][0]

    # Volatility: stddev of valence values, scaled to [0, 1] (typical stddev
    # tops out around 0.7 for very swingy days; clamp at 1.0).
    valences = [v for _, v in samples_list]
    if len(valences) < 2:
        volatility = 0.0
    else:
        sd = statistics.stdev(valences)
        # Scale: 0.5 stddev ≈ moderate, 1.0 stddev ≈ max swings
        volatility = max(0.0, min(1.0, sd / 1.0))

    # Sparkline: bucket by hour (0-23), average valence in each bucket.
    hourly: dict[int, list[float]] = {}
    for ts, val in samples_list:
        hour = int((ts // 3600) % 24)
        hourly.setdefault(hour, []).append(val)
    state_curve = []
    for h in range(24):
        bucket = hourly.get(h)
        if not bucket:
            continue
        state_curve.append(sum(bucket) / len(bucket))

    return DailyMoodAggregate(
        day_local_date=day_local_date,
        dominant_valence=dominant_valence,
        volatility_score=volatility,
        state_curve_compact=state_curve,
        event_count=len(samples_list),
        source_event_ids=normalized_source_event_ids,
        computed_at=time.time(),
    )
