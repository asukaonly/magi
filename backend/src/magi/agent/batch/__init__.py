"""Batch orchestrator: manifest-driven long-running batch processing (L12).

Phase 1 scope: contracts + manifest store. The engine is task-agnostic —
it only knows ``item`` rows; what "process one item" means lives in the
handler (a skill prompt), not here.
"""
from .contracts import (
    BatchItem,
    BatchItemStatus,
    BatchJob,
    BatchJobStatus,
    ItemOutcome,
    ReconcileReport,
    TERMINAL_ITEM_STATUSES,
)
from .store import BatchStore

__all__ = [
    "BatchItem",
    "BatchItemStatus",
    "BatchJob",
    "BatchJobStatus",
    "ItemOutcome",
    "ReconcileReport",
    "TERMINAL_ITEM_STATUSES",
    "BatchStore",
]
