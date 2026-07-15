"""Cross-store follow-ups for durable memory corrections."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .event_contracts import (
    AuthorType,
    ContentType,
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from .l2.corrections.repository import MemoryCorrectionRepository


class UnifiedMemoryCorrectionMixin:
    """Project user governance actions into the immutable L1 audit stream."""

    l1: Any
    memory_db_path: str

    async def write_l1_correction_audit(self, job: Mapping[str, Any]) -> None:
        """Write one non-cognitive, idempotent L1 audit event."""
        async with self.memory_operation_guard():  # type: ignore[attr-defined]
            await self._write_l1_correction_audit_guarded(job)

    async def _write_l1_correction_audit_guarded(self, job: Mapping[str, Any]) -> None:
        if self.l1 is None:
            raise RuntimeError("L1 memory is unavailable for correction audit")
        correction = await MemoryCorrectionRepository(self.memory_db_path).get(
            str(job["correction_id"])
        )
        if correction is None:
            raise RuntimeError("Correction record is missing for L1 audit")
        if correction.audit_event_id is None:
            raise RuntimeError("Correction record has no L1 audit event id")

        replacement = correction.replacement or {}
        content = json.dumps(
            {
                "target_kind": correction.target_kind.value,
                "target_id": correction.target_id,
                "correction_kind": correction.correction_kind.value,
                "replacement": replacement,
                "reason": correction.reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        event = MemoryEvent(
            event_id=correction.audit_event_id,
            correlation_id=correction.correction_id,
            timestamp=correction.created_at,
            created_at=correction.created_at,
            event_type="MEMORY_CORRECTION",
            source="memory_correction",
            source_item_id=correction.correction_id,
            memory_domain=MemoryDomain.INTERACTION,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=False,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.PERMANENT,
            session_id=None,
            turn_id=None,
            user_id=correction.actor_id,
            task_id=None,
            content=content,
            author_type=AuthorType.SYSTEM.label,
            content_type=ContentType.TEXT.label,
            importance_score=0.8,
            level=20,
            idempotency_key=f"memory_correction:{correction.correction_id}",
            metadata_json={
                "correction_id": correction.correction_id,
                "target_kind": correction.target_kind.value,
                "target_id": correction.target_id,
                "correction_kind": correction.correction_kind.value,
                "source_event_id": correction.source_event_id,
            },
        )
        stored_event_id = await self.l1.store(event)
        if stored_event_id != correction.audit_event_id:
            raise RuntimeError("Correction audit idempotency resolved to another event")


__all__ = ["UnifiedMemoryCorrectionMixin"]
