"""Benchmark-facing writer that replays normalized records into memory."""

from __future__ import annotations

from typing import Any

from ...events.events import Event, EventLevel, EventTypes
from .contracts import EvalMemoryWriteRecord


EVAL_EXTERNAL_OBSERVATION_EVENT_TYPE = "BenchmarkExternalObservation"


class EvalMemoryWriter:
    """Write benchmark replay records through the unified memory ingest path."""

    def __init__(self, unified_memory: Any) -> None:
        self._memory = unified_memory

    async def write_record(self, record: EvalMemoryWriteRecord) -> dict[str, Any]:
        event_type, author_type = self._resolve_role_mapping(record.role)
        payload = {
            "user_id": record.namespace,
            "session_id": record.session_id,
            "turn_id": record.turn_id,
            "content": record.content,
            "author_type": author_type,
            "content_type": "text",
            "runtime_namespace": "benchmark",
        }
        metadata = {
            "eval_namespace": record.namespace,
        }
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
            return EventTypes.USER_MESSAGE, "user"
        if normalized == "assistant":
            return EventTypes.AI_RESPONSE, "assistant"
        if normalized == "external":
            return EVAL_EXTERNAL_OBSERVATION_EVENT_TYPE, "external"
        raise ValueError(f"Unsupported eval replay role: {role}")
