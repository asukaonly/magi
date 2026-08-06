"""L2 cognition pipeline composition facade."""

from __future__ import annotations

from ..batching_policy import (
    DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH,
    DEFAULT_L2_MAX_EVENTS_PER_BATCH,
)
from ..models import ResolvedEntityMention
from .context import L2PipelineContextMixin
from .entities.resolution import L2EntityResolutionMixin
from .entities.side_effects import L2EntitySideEffectMixin
from .extraction import L2PipelineExtractionMixin
from .lifecycle import (
    DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS,
    DEFAULT_L2_EXTRACT_WORKER_COUNT,
    DEFAULT_L2_PROJECTION_CLAIM_LIMIT,
    DEFAULT_L2_PROJECTION_STALE_QUEUED_TIMEOUT_SECONDS,
    DEFAULT_L2_PROJECTION_STALE_RUNNING_TIMEOUT_SECONDS,
    L2PipelineLifecycleMixin,
    L2PipelineStats,
)
from .persistence import L2PipelinePersistenceMixin
from .queueing import (
    DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS,
    L2PipelineQueueMixin,
)
from .utils import L2PipelineUtilityMixin
from .validation import L2ValidationMixin
from .workers import L2PipelineWorkerMixin


class L2Pipeline(
    L2PipelineLifecycleMixin,
    L2PipelineUtilityMixin,
    L2PipelineQueueMixin,
    L2PipelineContextMixin,
    L2PipelineWorkerMixin,
    L2PipelineExtractionMixin,
    L2EntityResolutionMixin,
    L2EntitySideEffectMixin,
    L2PipelinePersistenceMixin,
    L2ValidationMixin,
):
    """Owns asynchronous L2 extraction and follow-up queues."""


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
