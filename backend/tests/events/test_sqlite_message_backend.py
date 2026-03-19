from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from magi.events.events import Event, EventTypes
from magi.events.sqlite_backend import (
    PROCESS_OUTCOME_COMPLETED,
    PROCESS_OUTCOME_REQUEUE,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
    STATUS_COMPLETED,
    STATUS_PENDING,
    SQLiteMessageBackend,
)


async def _read_message_row(db_path: Path) -> tuple[str, int] | None:
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            "SELECT status, retry_count FROM message_queue ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return str(row[0]), int(row[1])


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Timed out waiting for condition")


@pytest.mark.asyncio
async def test_critical_event_without_local_subscribers_requests_requeue(tmp_path: Path) -> None:
    db_path = tmp_path / "message_queue.db"
    backend = SQLiteMessageBackend(db_path=str(db_path), max_retries=3)
    await backend._init_db()

    await backend.publish(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={"response": "hello"},
            metadata={REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True},
        )
    )

    result = await backend._get_next_event()

    assert result is not None
    event_id, event = result
    outcome = await backend._process_event(event)

    assert outcome == PROCESS_OUTCOME_REQUEUE

    await backend._requeue_for_other_subscribers(event_id)
    assert await _read_message_row(db_path) == (STATUS_PENDING, 0)


@pytest.mark.asyncio
async def test_worker_requeues_critical_event_until_another_backend_handles_it(tmp_path: Path) -> None:
    db_path = tmp_path / "message_queue.db"
    first_backend = SQLiteMessageBackend(
        db_path=str(db_path),
        num_workers=1,
        max_retries=3,
        retry_delay_seconds=0.5,
    )
    second_backend = SQLiteMessageBackend(
        db_path=str(db_path),
        num_workers=1,
        max_retries=3,
        retry_delay_seconds=0.5,
    )
    received: list[str] = []

    async def _handler(event: Event) -> None:
        received.append(str(event.data.get("response")))

    await first_backend.start()
    try:
        await first_backend.publish(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"response": "done"},
                metadata={REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True},
            )
        )
        await _wait_for(
            lambda: _row_is_pending(db_path),
            timeout=2.0,
        )
        await second_backend.subscribe(EventTypes.AI_RESPONSE, _handler)
        await second_backend.start()

        await _wait_for(lambda: _event_delivered(db_path, received), timeout=3.0)

        assert received == ["done"]
        assert await _read_message_row(db_path) == (STATUS_COMPLETED, 0)
    finally:
        await second_backend.stop()
        await first_backend.stop()


async def _row_is_pending(db_path: Path) -> bool:
    return await _read_message_row(db_path) == (STATUS_PENDING, 0)


async def _event_delivered(db_path: Path, received: list[str]) -> bool:
    return bool(received) and await _read_message_row(db_path) == (STATUS_COMPLETED, 0)


@pytest.mark.asyncio
async def test_noncritical_event_without_local_subscribers_still_completes(tmp_path: Path) -> None:
    db_path = tmp_path / "message_queue.db"
    backend = SQLiteMessageBackend(db_path=str(db_path), max_retries=3)
    await backend._init_db()

    await backend.publish(
        Event(
            type="NonCriticalEvent",
            data={"value": 1},
        )
    )

    result = await backend._get_next_event()

    assert result is not None
    event_id, event = result
    outcome = await backend._process_event(event)

    assert outcome == PROCESS_OUTCOME_COMPLETED

    await backend._mark_completed(event_id)
    assert await _read_message_row(db_path) == (STATUS_COMPLETED, 0)
