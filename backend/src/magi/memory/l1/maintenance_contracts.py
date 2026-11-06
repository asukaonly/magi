"""Storage-neutral maintenance scans and conditional evidence updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ports import EventEvidence, MemoryEventRecord


from magi_plugin_sdk.storage_models.event_maintenance import (
    EvidenceBackfillQuery,
    EventScanItem,
    EvidenceAnnotationUpdate,
    EventClearState,
)
