"""Tests for eval-support memory writer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.events.events import EventTypes
from magi.memory.eval_support.contracts import EvalMemoryWriteRecord
from magi.memory.eval_support.writer import EvalMemoryWriter


@pytest.mark.asyncio
async def test_writer_maps_user_and_assistant_roles_into_ingest_events() -> None:
    unified_memory = AsyncMock()
    unified_memory.ingest_event = AsyncMock(return_value={"event_id": "evt-1"})
    writer = EvalMemoryWriter(unified_memory)

    user_record = EvalMemoryWriteRecord(
        namespace="benchmark/longmemeval/run-1/q-1",
        session_id="session-1",
        turn_id="turn-1",
        timestamp=100.0,
        role="user",
        content="hello",
    )
    assistant_record = EvalMemoryWriteRecord(
        namespace="benchmark/longmemeval/run-1/q-1",
        session_id="session-1",
        turn_id="turn-2",
        timestamp=101.0,
        role="assistant",
        content="hi",
    )

    await writer.write_record(user_record)
    await writer.write_record(assistant_record)

    first_event = unified_memory.ingest_event.await_args_list[0].args[0]
    second_event = unified_memory.ingest_event.await_args_list[1].args[0]

    assert first_event.type == EventTypes.USER_MESSAGE
    assert first_event.data["user_id"] == user_record.namespace
    assert first_event.data["session_id"] == "session-1"
    assert first_event.data["message"] == "hello"
    assert first_event.metadata["turn_id"] == "turn-1"

    assert second_event.type == EventTypes.AI_RESPONSE
    assert second_event.data["user_id"] == assistant_record.namespace
    assert second_event.data["session_id"] == "session-1"
    assert second_event.data["response"] == "hi"
    assert second_event.metadata["turn_id"] == "turn-2"


@pytest.mark.asyncio
async def test_writer_preserves_input_order_when_writing_multiple_records() -> None:
    unified_memory = AsyncMock()
    unified_memory.ingest_event = AsyncMock(return_value={"event_id": "evt-1"})
    writer = EvalMemoryWriter(unified_memory)
    records = [
        EvalMemoryWriteRecord(
            namespace="benchmark/longmemeval/run-1/q-1",
            session_id="session-1",
            turn_id=f"turn-{index}",
            timestamp=float(index),
            role="user",
            content=f"msg-{index}",
        )
        for index in [2, 1, 3]
    ]

    await writer.write_records(records)

    written_turn_ids = [call.args[0].metadata["turn_id"] for call in unified_memory.ingest_event.await_args_list]
    assert written_turn_ids == ["turn-1", "turn-2", "turn-3"]
