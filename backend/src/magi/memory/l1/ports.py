"""Storage-neutral commands for the atomic L1 event boundary."""

from __future__ import annotations

from typing import Protocol

from magi_plugin_sdk.storage_models.event_records import (
    EventEvidence as EventEvidence,
    EventAppend as EventAppend,
    EventAppendResult as EventAppendResult,
    EventDeletionPlan as EventDeletionPlan,
    EventVisibility as EventVisibility,
    MemoryEventRecord as MemoryEventRecord,
    EventQuery as EventQuery,
    EventEvidenceReference as EventEvidenceReference,
    EventSourceIdentity as EventSourceIdentity,
)

from magi_plugin_sdk.storage_ports.events import EventStorageOperations

class MemoryEventRepository(EventStorageOperations, Protocol):
    """The memory domain consumes the complete event persistence contract."""
