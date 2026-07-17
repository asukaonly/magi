"""Project manual entries to L1 events.

Manual entries are stored in their own table but ALSO mirrored to the
L1 event stream so the rest of the memory pipeline (episode formation,
cluster_builder, themes, mood aggregate, diary LLM) picks them up
without any parallel ingestion path.

Each projection is immutable. Replacements get a deterministic idempotency
key derived from the predecessor event and the current projected content, so a
retry after a partial route failure resolves the same L1 row instead of
creating another copy.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

from magi.events.sensor_activity_snapshot import ACTIVITY_SNAPSHOT_METADATA_KEY

from ..event_contracts import (
    AuthorType,
    ContentType,
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
    author_type_code,
    content_type_code,
)
from .models import ManualEntry


class _GovernedL1WriteProtocol(Protocol):
    async def store_governed_l1_event(self, event: MemoryEvent) -> str | None: ...


# Event type tag used by L1 + downstream consumers. Distinct from
# sensor-derived events so episode_formation / themes can apply special
# handling if needed (currently they don't — manual entries flow through
# the same pipeline as sensor events).
MANUAL_ENTRY_EVENT_TYPE = "manual_entry.note"


def _projection_fingerprint(entry: ManualEntry) -> str:
    projected = {
        "event_at": float(entry.event_at),
        "body": entry.body,
        "mood": entry.mood,
        "attachments": list(entry.attachments),
        "location_label": entry.location_label,
        "exclude_from_llm": bool(entry.exclude_from_llm),
        "weather": dict(entry.weather) if entry.weather else None,
    }
    payload = json.dumps(
        projected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _idempotency_key(entry: ManualEntry, predecessor_event_id: str | None) -> str:
    predecessor = str(predecessor_event_id or "initial").strip() or "initial"
    return f"manual-entry:{entry.entry_id}:{predecessor}:{_projection_fingerprint(entry)}"


def _projection_event_id(entry: ManualEntry, predecessor_event_id: str | None) -> str:
    identity = _idempotency_key(entry, predecessor_event_id).encode("utf-8")
    return f"me_{hashlib.sha256(identity).hexdigest()[:32]}"


def _build_memory_event(
    entry: ManualEntry,
    *,
    predecessor_event_id: str | None,
) -> MemoryEvent:
    """Compose a MemoryEvent for a single manual_entries row.

    timestamp = ``event_at`` (when the memory happened), NOT ``created_at``
    — this is what positions it in the timeline view.
    """
    metadata: dict[str, Any] = {
        ACTIVITY_SNAPSHOT_METADATA_KEY: {
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
            # Ambient weather snapshot — present when the fetcher could
            # resolve coords + reach Open-Meteo. Downstream (themes /
            # diary LLM) can use it as soft context ("on a rainy day…")
            # without us prescribing a particular prompt shape.
            "weather": dict(entry.weather) if entry.weather else None,
        },
    }
    now = time.time()
    return MemoryEvent(
        event_id=_projection_event_id(entry, predecessor_event_id),
        correlation_id=f"manual-entry:{entry.entry_id}",
        timestamp=float(entry.event_at),
        created_at=now,
        event_type=MANUAL_ENTRY_EVENT_TYPE,
        source="manual_entry",
        source_item_id=entry.entry_id,
        memory_domain=MemoryDomain.USER_AUTHORED,
        ingest_target=IngestTarget.L0_AND_L1,
        cognition_eligible=not entry.exclude_from_llm,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.PERMANENT,
        session_id=None,
        turn_id=None,
        user_id=None,
        task_id=None,
        content=entry.body,
        author_type=author_type_code(AuthorType.USER),
        content_type=content_type_code(ContentType.TEXT),
        importance_score=0.75,  # user-authored = high baseline importance
        level=0,
        idempotency_key=_idempotency_key(entry, predecessor_event_id),
        metadata_json=metadata,
    )


class ManualEntryL1Projector:
    """Wraps the L1 event store with manual-entry-shaped helpers."""

    def __init__(self, *, memory: _GovernedL1WriteProtocol) -> None:
        self._memory = memory

    @staticmethod
    def event_id_for(
        entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> str | None:
        """Return the stable identity for a retryable projection."""
        return _projection_event_id(entry, predecessor_event_id)

    async def project_current(
        self,
        entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> str:
        """Persist the current projection and return its stable event id."""
        event = _build_memory_event(
            entry,
            predecessor_event_id=predecessor_event_id,
        )
        return await self._memory.store_governed_l1_event(event)
