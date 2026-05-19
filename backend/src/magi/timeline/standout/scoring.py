"""Heuristic scoring for magi_standout / standout_score / standout_reason.

The function is pure — no I/O. The caller (T7's scheduler job) gathers
the necessary signals from the L2 store + MediaSourceRegistry and passes
them in. Tuning weights in the future is a single-file change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


# Weights — tuning happens here.
WEIGHT_DURATION = 0.35
WEIGHT_PHOTOS = 0.30
WEIGHT_STATE_SHIFT = 0.20
WEIGHT_FIRST_ENTITY_EACH = 0.30
WEIGHT_FIRST_ENTITY_CAP = 0.45

DURATION_THRESHOLD_SECONDS = 90 * 60  # 90 minutes
STANDOUT_THRESHOLD = 0.50


@dataclass(slots=True)
class StandoutSignals:
    """External signals collected by the caller."""

    has_photos: bool = False
    state_shift_count: int = 0
    first_seen_entities: list[str] = field(default_factory=list)


def compute_standout_score(
    *,
    episode: Mapping[str, Any],
    signals: StandoutSignals,
) -> tuple[float, str, bool]:
    """Return (score, reason, is_standout) for an episode.

    `score` is clamped to [0.0, 1.0]. `reason` is a ;-joined list of
    contributing signal tags (e.g. "duration[N min];photos;first_entity[x,y]").
    `is_standout` is True iff score >= STANDOUT_THRESHOLD.
    """
    score = 0.0
    reasons: list[str] = []

    # Duration
    duration_seconds = max(
        0.0,
        float(episode.get("time_end") or 0.0) - float(episode.get("time_start") or 0.0),
    )
    if duration_seconds >= DURATION_THRESHOLD_SECONDS:
        score += WEIGHT_DURATION
        minutes = int(duration_seconds // 60)
        reasons.append(f"duration[{minutes}min]")

    # Photos
    if signals.has_photos:
        score += WEIGHT_PHOTOS
        reasons.append("photos")

    # State shifts
    shift_count = max(0, int(signals.state_shift_count or 0))
    if shift_count > 0:
        score += WEIGHT_STATE_SHIFT
        reasons.append(f"state_shift[{shift_count}]")

    # First-occurrence entities
    firsts = [e for e in (signals.first_seen_entities or []) if e]
    if firsts:
        entity_score = min(WEIGHT_FIRST_ENTITY_CAP, len(firsts) * WEIGHT_FIRST_ENTITY_EACH)
        score += entity_score
        # Show up to 3 entity ids in the reason for traceability
        sample = ",".join(firsts[:3])
        reasons.append(f"first_entity[{sample}]")

    score = max(0.0, min(1.0, score))
    reason = ";".join(reasons) if reasons else "no signals"
    is_standout = score >= STANDOUT_THRESHOLD
    return score, reason, is_standout
