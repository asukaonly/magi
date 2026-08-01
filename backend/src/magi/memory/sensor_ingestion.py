"""Authoritative sensor-event commit boundary for durable memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..events.domain_payloads import SensorEventEmitted
from ..events.events import Event, EventTypes
from ..events.payload_helpers import expect_payload
from .clear_generation import current_memory_clear_state
from .sensor_event_projection import build_sensor_memory_event


class SensorCommitOutcome(str, Enum):
    """Terminal outcomes accepted by the sensor sync cursor contract."""

    PERSISTED = "persisted"
    DUPLICATE = "duplicate"
    GOVERNED_SKIP = "governed_skip"


@dataclass(frozen=True, slots=True)
class SensorCommitReceipt:
    """Proof that one sensor event reached a terminal L1-owned outcome."""

    event_id: str
    outcome: SensorCommitOutcome
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SensorIngestionBoundary:
    """Clear state captured atomically before one source batch starts."""

    expected_epoch: int
    clear_generation: int
    clear_cutoff_at: float


class SensorCommitDeferredError(RuntimeError):
    """Raised when a sensor event must be retried before its cursor can advance."""


class SensorEventCommitter:
    """Commit sensor events synchronously and return an explicit durable receipt."""

    _GOVERNED_SKIP_REASONS = frozenset(
        {
            "memory_clear_epoch_changed",
            "source_event_forgotten",
            "time_range_forgotten",
        }
    )

    def __init__(self, *, unified_memory: Any) -> None:
        self._unified_memory = unified_memory

    async def capture_ingestion_boundary(self) -> SensorIngestionBoundary:
        """Capture process and durable clear state in one admitted operation."""

        async with self._unified_memory.memory_operation_guard():
            expected_epoch = int(self._unified_memory.memory_operation_epoch())
            generation, cutoff_at = await current_memory_clear_state(
                str(self._unified_memory.memory_db_path)
            )
        return SensorIngestionBoundary(
            expected_epoch=expected_epoch,
            clear_generation=generation,
            clear_cutoff_at=cutoff_at,
        )

    async def commit(
        self,
        event: Event,
        *,
        expected_epoch: int,
        clear_generation: int,
        clear_cutoff_at: float,
        allow_pre_clear_events: bool,
    ) -> SensorCommitReceipt:
        """Commit one sensor event or raise without granting cursor progress."""

        if event.type != EventTypes.SENSOR_EVENT_EMITTED:
            raise ValueError(f"Unsupported sensor commit event type: {event.type}")
        payload = expect_payload(event, SensorEventEmitted)
        memory_event = build_sensor_memory_event(
            payload,
            event_id=str(event.event_id),
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
        )
        if (
            int(clear_generation) > 0
            and not allow_pre_clear_events
            and float(memory_event.timestamp) <= float(clear_cutoff_at)
        ):
            return SensorCommitReceipt(
                event_id=str(event.event_id),
                outcome=SensorCommitOutcome.GOVERNED_SKIP,
                skip_reason="memory_clear_cutoff",
            )
        result = await self._unified_memory.ingest_event(
            memory_event,
            expected_epoch=int(expected_epoch),
        )
        skip_reason = str(result.get("skip_reason") or "")
        if skip_reason in self._GOVERNED_SKIP_REASONS:
            return SensorCommitReceipt(
                event_id=str(result.get("event_id") or event.event_id),
                outcome=SensorCommitOutcome.GOVERNED_SKIP,
                skip_reason=skip_reason,
            )
        if result.get("skipped"):
            raise SensorCommitDeferredError(
                f"Sensor memory commit deferred: {skip_reason or 'unknown'}"
            )
        if not bool(result.get("l1_confirmed")):
            raise SensorCommitDeferredError(
                "Sensor memory commit completed without L1 confirmation"
            )
        return SensorCommitReceipt(
            event_id=str(result.get("event_id") or event.event_id),
            outcome=(
                SensorCommitOutcome.PERSISTED
                if bool(result.get("l1_written"))
                else SensorCommitOutcome.DUPLICATE
            ),
        )


__all__ = [
    "SensorCommitDeferredError",
    "SensorCommitOutcome",
    "SensorCommitReceipt",
    "SensorIngestionBoundary",
    "SensorEventCommitter",
]
