"""L2 pipeline public facade."""

from __future__ import annotations

from typing import Any

__all__ = [
    "DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS",
    "DEFAULT_L2_EXTRACT_WORKER_COUNT",
    "DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS",
    "DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH",
    "DEFAULT_L2_MAX_EVENTS_PER_BATCH",
    "DEFAULT_L2_PROJECTION_CLAIM_LIMIT",
    "DEFAULT_L2_PROJECTION_STALE_QUEUED_TIMEOUT_SECONDS",
    "DEFAULT_L2_PROJECTION_STALE_RUNNING_TIMEOUT_SECONDS",
    "L2Pipeline",
    "L2PipelineStats",
    "ResolvedEntityMention",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
