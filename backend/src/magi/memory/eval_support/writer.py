"""Benchmark-facing writer that replays normalized records into memory."""

from __future__ import annotations

from typing import Any

from ...events.events import Event, EventLevel, EventTypes
from .contracts import EvalMemoryWriteRecord


class EvalMemoryWriter:
    """Write benchmark replay records through the unified memory ingest path."""

    def __init__(self, unified_memory: Any) -> None:
        self._memory = unified_memory

    async def write_record(self, record: EvalMemoryWriteRecord) -> dict[str, Any]:
        event_type, payload_key = self._resolve_role_mapping(record.role)
        payload = {
            "user_id": record.namespace,
            "session_id": record.session_id,
            payload_key: record.content,
            "runtime_namespace": "benchmark",
        }
        metadata = {
            "eval_namespace": record.namespace,
        }
        if record.turn_id is not None:
            metadata["turn_id"] = record.turn_id
        if record.metadata:
            metadata.update(record.metadata)

        event = Event(
            type=event_type,
            data=payload,
            timestamp=float(record.timestamp),
            source="benchmark.eval_support",
            level=EventLevel.INFO,
            metadata=metadata,
            correlation_id=str(record.turn_id or f"{record.session_id}:{record.timestamp}"),
        )
        return await self._memory.ingest_event(event)

    async def write_records(self, records: list[EvalMemoryWriteRecord]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for record in sorted(records, key=lambda item: item.timestamp):
            results.append(await self.write_record(record))
        return results

    @staticmethod
    def _resolve_role_mapping(role: str) -> tuple[str, str]:
        normalized = str(role).strip().lower()
        if normalized == "user":
            return EventTypes.USER_MESSAGE, "message"
        if normalized == "assistant":
            return EventTypes.AI_RESPONSE, "response"
        raise ValueError(f"Unsupported eval replay role: {role}")
