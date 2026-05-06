"""Single source of truth for L2 micro-batch flush decisions.

Both the in-memory staging path (`pipeline/staging.py`) and the durable
projection-claim path (`projection/claiming.py`) call into `decide_flush`
to decide whether a bucket has grown enough or waited long enough to be
extracted. Keeping the rule in one place prevents the two paths from
drifting (which is how the chat-message-not-batching bug got introduced).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


DEFAULT_L2_MAX_EVENTS_PER_BATCH = 12
DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH = 2400
DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS = 60.0


class FlushReason(str, Enum):
    MAX_EVENTS = "max_events"
    TOKEN_CAP = "token_cap"
    INTERVAL_ELAPSED = "interval_elapsed"


@dataclass(frozen=True, slots=True)
class BatchingPolicy:
    max_events: int = DEFAULT_L2_MAX_EVENTS_PER_BATCH
    max_estimated_tokens: int = DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH
    max_wait_seconds: float = DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS
    min_ready_events: int | None = None
    """Lower-than-max trigger threshold. None means trigger == max_events.

    The projection-claim path uses this to flush a partially-full bucket once
    enough events accumulate, without waiting all the way to max_events.
    """


@dataclass(frozen=True, slots=True)
class BucketState:
    event_count: int
    estimated_tokens: int
    oldest_age_seconds: float


def decide_flush(
    state: BucketState,
    policy: BatchingPolicy,
    *,
    batching_enabled: bool,
) -> FlushReason | None:
    """Return the reason to flush this bucket, or None to keep waiting.

    Priority order is fixed (max_events > token_cap > interval_elapsed) so
    `batch_flush_by_reason` telemetry remains comparable across releases.
    """
    if state.event_count <= 0:
        return None
    trigger = policy.min_ready_events if policy.min_ready_events is not None else policy.max_events
    trigger = max(1, min(int(trigger), policy.max_events))
    if state.event_count >= trigger:
        return FlushReason.MAX_EVENTS
    if state.estimated_tokens >= policy.max_estimated_tokens:
        return FlushReason.TOKEN_CAP
    if not batching_enabled:
        return FlushReason.INTERVAL_ELAPSED
    if max(0.0, state.oldest_age_seconds) >= policy.max_wait_seconds:
        return FlushReason.INTERVAL_ELAPSED
    return None


__all__ = [
    "BatchingPolicy",
    "BucketState",
    "DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS",
    "DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH",
    "DEFAULT_L2_MAX_EVENTS_PER_BATCH",
    "FlushReason",
    "decide_flush",
]
