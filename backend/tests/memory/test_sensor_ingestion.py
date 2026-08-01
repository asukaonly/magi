"""Tests for the authoritative sensor-to-L1 commit boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.events.domain_payloads import SensorEventEmitted, TaskContext
from magi.events.events import Event, EventTypes
from magi.memory.sensor_ingestion import (
    SensorCommitDeferredError,
    SensorCommitOutcome,
    SensorCommitReceipt,
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


async def _commit(
    committer: SensorEventCommitter,
    *,
    clear_generation: int = 0,
    clear_cutoff_at: float = 0.0,
    allow_pre_clear_events: bool = False,
) -> SensorCommitReceipt:
    return await committer.commit(
        _sensor_event(),
        expected_epoch=7,
        clear_generation=clear_generation,
        clear_cutoff_at=clear_cutoff_at,
        allow_pre_clear_events=allow_pre_clear_events,
    )


@pytest.mark.asyncio
async def test_commit_returns_persisted_receipt_after_l1_confirmation() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": True,
        "l1_confirmed": True,
    }

    receipt = await _commit(SensorEventCommitter(unified_memory=memory))

    assert receipt.event_id == "sensor-event-1"
    assert receipt.outcome is SensorCommitOutcome.PERSISTED
    memory.ingest_event.assert_awaited_once()
    assert memory.ingest_event.await_args.kwargs["expected_epoch"] == 7


@pytest.mark.asyncio
async def test_commit_returns_canonical_duplicate_receipt() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "existing-event",
        "l1_written": False,
        "l1_confirmed": True,
    }

    receipt = await _commit(SensorEventCommitter(unified_memory=memory))

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

    receipt = await _commit(SensorEventCommitter(unified_memory=memory))

    assert receipt.outcome is SensorCommitOutcome.GOVERNED_SKIP
    assert receipt.skip_reason == skip_reason


@pytest.mark.asyncio
async def test_memory_clear_epoch_change_is_a_terminal_accepted_outcome() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": False,
        "l1_confirmed": False,
        "skipped": True,
        "skip_reason": "memory_clear_epoch_changed",
    }

    receipt = await _commit(SensorEventCommitter(unified_memory=memory))

    assert receipt.outcome is SensorCommitOutcome.GOVERNED_SKIP
    assert receipt.skip_reason == "memory_clear_epoch_changed"


@pytest.mark.asyncio
async def test_pre_clear_source_event_is_skipped_without_touching_memory() -> None:
    memory = AsyncMock()

    receipt = await _commit(
        SensorEventCommitter(unified_memory=memory),
        clear_generation=3,
        clear_cutoff_at=1_700_000_000.0,
    )

    assert receipt.outcome is SensorCommitOutcome.GOVERNED_SKIP
    assert receipt.skip_reason == "memory_clear_cutoff"
    memory.ingest_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_clear_source_event_is_persisted() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": True,
        "l1_confirmed": True,
    }

    receipt = await _commit(
        SensorEventCommitter(unified_memory=memory),
        clear_generation=3,
        clear_cutoff_at=1_699_999_999.0,
    )

    assert receipt.outcome is SensorCommitOutcome.PERSISTED
    memory.ingest_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_history_import_may_restore_pre_clear_source_event() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": True,
        "l1_confirmed": True,
    }

    receipt = await _commit(
        SensorEventCommitter(unified_memory=memory),
        clear_generation=3,
        clear_cutoff_at=1_700_000_000.0,
        allow_pre_clear_events=True,
    )

    assert receipt.outcome is SensorCommitOutcome.PERSISTED
    memory.ingest_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_l1_confirmation_requires_retry() -> None:
    memory = AsyncMock()
    memory.ingest_event.return_value = {
        "event_id": "sensor-event-1",
        "l1_written": False,
        "l1_confirmed": False,
    }

    with pytest.raises(SensorCommitDeferredError, match="without L1 confirmation"):
        await _commit(SensorEventCommitter(unified_memory=memory))


@pytest.mark.asyncio
async def test_l1_exception_propagates_to_sensor_job() -> None:
    memory = AsyncMock()
    memory.ingest_event.side_effect = OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        await _commit(SensorEventCommitter(unified_memory=memory))
