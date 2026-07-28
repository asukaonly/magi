"""Tests for the authoritative sensor-to-L1 commit boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.events.domain_payloads import SensorEventEmitted, TaskContext
from magi.events.events import Event, EventTypes
from magi.memory.sensor_ingestion import (
    SensorCommitDeferredError,
    SensorCommitOutcome,
    SensorEventCommitter,
)


def _sensor_event() -> Event:
    payload = SensorEventEmitted(
        sensor_name="test.sensor",
        sensor_id="test.sensor",
        payload={},
        output_dict={
            "source_type": "test_source",
            "source_item_id": "item-1",
            "occurred_at": 1_700_000_000.0,
            "captured_at": 1_700_000_001.0,
        },
        context=TaskContext(
            session_id=None,
            turn_id=None,
            task_id=None,
            user_id="local_user",
        ),
        policy_dict={
            "memory_domain": "external_activity",
            "ingest_target": "l1_only",
        },
        projection_dict={"content": "Observed item"},
        owner_user_id="local_user",
        idempotency_key="item-1",
        memory_event_type="TEST_SENSOR_EVENT",
    )
    return Event(
        type=EventTypes.SENSOR_EVENT_EMITTED,
        data=payload,
        event_id="sensor-event-1",
        source="test",
    )


@pytest.mark.asyncio
async def test_commit_returns_persisted_receipt_after_l1_confirmation() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": True,
        "l1_confirmed": True,
    }

    receipt = await SensorEventCommitter(unified_memory=memory).commit(_sensor_event())

    assert receipt.event_id == "sensor-event-1"
    assert receipt.outcome is SensorCommitOutcome.PERSISTED


@pytest.mark.asyncio
async def test_commit_returns_canonical_duplicate_receipt() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "existing-event",
        "l1_written": False,
        "l1_confirmed": True,
    }

    receipt = await SensorEventCommitter(unified_memory=memory).commit(_sensor_event())

    assert receipt.event_id == "existing-event"
    assert receipt.outcome is SensorCommitOutcome.DUPLICATE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skip_reason",
    ["source_event_forgotten", "time_range_forgotten"],
)
async def test_governed_skip_is_a_terminal_accepted_outcome(skip_reason: str) -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": False,
        "l1_confirmed": False,
        "skipped": True,
        "skip_reason": skip_reason,
    }

    receipt = await SensorEventCommitter(unified_memory=memory).commit(_sensor_event())

    assert receipt.outcome is SensorCommitOutcome.GOVERNED_SKIP


@pytest.mark.asyncio
async def test_memory_clear_race_requires_retry() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": False,
        "l1_confirmed": False,
        "skipped": True,
        "skip_reason": "memory_clear_epoch_changed",
    }

    with pytest.raises(SensorCommitDeferredError, match="memory_clear_epoch_changed"):
        await SensorEventCommitter(unified_memory=memory).commit(_sensor_event())


@pytest.mark.asyncio
async def test_missing_l1_confirmation_requires_retry() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": False,
        "l1_confirmed": False,
    }

    with pytest.raises(SensorCommitDeferredError, match="without L1 confirmation"):
        await SensorEventCommitter(unified_memory=memory).commit(_sensor_event())


@pytest.mark.asyncio
async def test_l1_exception_propagates_to_sensor_job() -> None:
    memory = AsyncMock()
    memory.ingest_event.side_effect = OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        await SensorEventCommitter(unified_memory=memory).commit(_sensor_event())
