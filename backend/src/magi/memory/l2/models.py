"""Contracts for the asynchronous L2 cognition pipeline."""

from __future__ import annotations

import time as time

from .batch_models import (
    L2BatchEvent,
    L2BatchJob,
    L2EntityReconcileJob,
    L2EventWindow,
    L2EventWindowSummary,
    L2HistoryContext,
    L2PendingBatchBucket,
    L2ProjectionLease,
    L2SnapshotRefreshJob,
    ManualL2EventRequest,
    PROJECTION_ATTEMPT_DESCRIPTOR_VERSION,
    build_l2_batch_bucket_key,
    derive_projection_attempt_key,
    projection_attempt_descriptor_json,
)
from .candidate_models import (
    L2GraphCandidate,
)
from .entities.models import (
    L2BatchEntityResolutionItem,
    L2EntityCandidate,
    L2EntityResolution,
    L2EntityResolutionMention,
    L2ExistingRecord,
    L2FocalEntityRef,
    L2KnowledgeEdgeWrite,
    L2SourceEvent,
    L2TomAssertionWrite,
    ResolvedEntityMention,
)
from .episode_models import EpisodeCandidateJob, EpisodeConsolidationStats, EpisodeWrite
from .phase_models import (
    ContradictionHint,
    L2ClaimEvidenceMode,
    L2FactKind,
    L2Phase1Entity,
    L2Phase1FactClaim,
    L2Phase1ResolvedRef,
    L2Phase1Result,
    L2Phase2Result,
    L2Phase2Summary,
    ReconciledTraitOutcome,
    StructuredEntityHint,
    StructuredGraphHint,
)


__all__ = [
    "PROJECTION_ATTEMPT_DESCRIPTOR_VERSION",
    "build_l2_batch_bucket_key",
    "derive_projection_attempt_key",
    "projection_attempt_descriptor_json",
    "ContradictionHint",
    "EpisodeCandidateJob",
    "EpisodeConsolidationStats",
    "EpisodeWrite",
    "L2BatchEvent",
    "L2BatchEntityResolutionItem",
    "L2BatchJob",
    "L2ClaimEvidenceMode",
    "L2FactKind",
    "L2EntityCandidate",
    "L2EntityResolution",
    "L2EntityResolutionMention",
    "L2EntityReconcileJob",
    "L2ExistingRecord",
    "L2EventWindow",
    "L2EventWindowSummary",
    "L2FocalEntityRef",
    "L2GraphCandidate",
    "L2HistoryContext",
    "L2KnowledgeEdgeWrite",
    "L2PendingBatchBucket",
    "L2ProjectionLease",
    "L2Phase1Entity",
    "L2Phase1FactClaim",
    "L2Phase1ResolvedRef",
    "L2Phase1Result",
    "L2Phase2Result",
    "L2Phase2Summary",
    "L2SnapshotRefreshJob",
    "L2SourceEvent",
    "L2TomAssertionWrite",
    "ManualL2EventRequest",
    "ReconciledTraitOutcome",
    "ResolvedEntityMention",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
