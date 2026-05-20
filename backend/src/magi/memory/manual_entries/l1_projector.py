"""Project manual entries to L1 events.

Manual entries are stored in their own table but ALSO mirrored to the
L1 event stream so the rest of the memory pipeline (episode formation,
cluster_builder, themes, mood aggregate, diary LLM) picks them up
without any parallel ingestion path.

Idempotency: each save gets a unique key
``manual-entry:{entry_id}:{timestamp_ns}``. On edit we tombstone the old
L1 row and store a fresh one — cleaner than racing with embedding
workers on an in-place update.

Soft-delete: cascades to L1 via ``mark_deleted``.
"""

from __future__ import annotations

import time
from typing import Any, Optional, Protocol

from ..event_contracts import MemoryEvent
from .models import ManualEntry


class _L1WriteProtocol(Protocol):
    async def store(self, event: MemoryEvent) -> str: ...
    async def mark_deleted(self, event_id: str, *, deleted_at: Optional[float] = None) -> bool: ...


def _idempotency_key(entry_id: str) -> str:
    # Time-based suffix so each save is unique (entries are immutable from
    # L1's perspective; updates manifest as new rows + tombstoned old ones).
    return f"manual-entry:{entry_id}:{time.time_ns()}"


def _build_memory_event(entry: ManualEntry) -> MemoryEvent:
    """Compose a MemoryEvent for a single manual_entries row.

    timestamp = ``event_at`` (when the memory happened), NOT ``created_at``
    — this is what positions it in the timeline view.
    """
    metadata: dict[str, Any] = {
        "timeline": {
            "title": "你写下的",
            "source_type": "manual_entry",
            "summary": entry.body,
        },
        "manual_entry": {
            "entry_id": entry.entry_id,
            "mood": entry.mood,
            "attachments": list(entry.attachments),
            "location_label": entry.location_label,
            "exclude_from_llm": entry.exclude_from_llm,
        },
    }
    return MemoryEvent(
        event_id="",  # store assigns
        timestamp=float(entry.event_at),
        source="manual_entry",
        content=entry.body,
        idempotency_key=_idempotency_key(entry.entry_id),
        metadata_json=metadata,
    )


class ManualEntryL1Projector:
    """Wraps the L1 event store with manual-entry-shaped helpers."""

    def __init__(self, *, l1_store: _L1WriteProtocol) -> None:
        self._l1 = l1_store

    async def project_on_create(self, entry: ManualEntry) -> str:
        """Emit the initial L1 event. Returns the assigned event_id."""
        event = _build_memory_event(entry)
        return await self._l1.store(event)

    async def project_on_update(self, entry: ManualEntry) -> str:
        """Tombstone the old L1 row (if any) and store a fresh one."""
        if entry.l1_event_id:
            await self._l1.mark_deleted(entry.l1_event_id, deleted_at=time.time())
        event = _build_memory_event(entry)
        return await self._l1.store(event)

    async def project_on_delete(self, entry: ManualEntry) -> None:
        """Soft-delete the L1 row tied to this entry, if any."""
        if entry.l1_event_id:
            await self._l1.mark_deleted(entry.l1_event_id, deleted_at=time.time())
