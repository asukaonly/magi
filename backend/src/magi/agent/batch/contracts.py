"""Typed contracts for the batch orchestrator manifest.

task-agnostic: no field here knows about "movies". ``input`` and
``result`` are opaque JSON blobs owned by the task handler.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from magi_plugin_sdk.run_trigger import RunTrigger


@dataclass(frozen=True, slots=True)
class BatchRunIdentity:
    """Persisted job and lease ownership for one background batch run."""

    job_id: str
    lease_owner: str

    @classmethod
    def from_trigger(cls, trigger: RunTrigger | None) -> BatchRunIdentity | None:
        if trigger is None or trigger.trigger_type != "batch":
            return None
        if len(trigger.correlation) != 1:
            raise ValueError("Batch trigger must identify exactly one job")
        job_id = trigger.correlation[0]
        lease_owner = trigger.payload.get("lease_owner")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("Batch trigger must contain a job ID")
        if not isinstance(lease_owner, str) or not lease_owner.strip():
            raise ValueError("Batch trigger must contain a lease owner")
        return cls(job_id=job_id, lease_owner=lease_owner)


class BatchJobStatus(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    RECONCILING = "reconciling"
    DONE = "done"
    FAILED = "failed"


class BatchItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    SKIPPED = "skipped"


TERMINAL_ITEM_STATUSES: frozenset[BatchItemStatus] = frozenset(
    {BatchItemStatus.DONE, BatchItemStatus.FAILED, BatchItemStatus.SKIPPED}
)


@dataclass(frozen=True, slots=True)
class BatchJob:
    job_id: str
    title: str
    owner: str
    origin_session_id: str
    origin_turn_id: str
    handler_ref: str
    handler_config: dict[str, Any]
    seed_spec: dict[str, Any]
    status: BatchJobStatus
    batch_size: int
    concurrency: int
    max_attempts: int
    reconcile_rounds_max: int
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class BatchItem:
    job_id: str
    item_id: str
    input: dict[str, Any]
    status: BatchItemStatus
    attempts: int
    result: dict[str, Any] | None
    error: str | None
    review_reason: str | None
    review_decision: dict[str, Any] | None
    lease_owner: str | None
    lease_expires_at_ms: int | None
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class ItemOutcome:
    """An agent-reported result for one item, consumed by update_items."""

    item_id: str
    status: BatchItemStatus
    result: dict[str, Any] | None = None
    review_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    job_id: str
    counts: dict[str, int]
    total: int
    conflicts: list[tuple[str, str]]
    reclaimed_leases: int
    complete: bool
