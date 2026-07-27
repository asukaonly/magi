from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from types import SimpleNamespace

import pytest

from magi.memory.l0.attention_update_scheduler import (
    AcceptedL0AttentionTurn,
    AttentionBatch,
    L0AttentionUpdateScheduler,
    should_update_attention_immediately,
)


def _config(
    *,
    turn_threshold: int = 3,
    idle_seconds: float = 10.0,
    max_delay_seconds: float = 20.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        attention_update_turn_threshold=turn_threshold,
        attention_update_idle_seconds=idle_seconds,
        attention_update_max_delay_seconds=max_delay_seconds,
    )


def _turn(
    turn_id: str,
    *,
    session_id: str = "session-1",
    epoch: int = 1,
    immediate: bool = False,
) -> AcceptedL0AttentionTurn:
    return AcceptedL0AttentionTurn(
        user_id="local-user",
        session_id=session_id,
        turn_id=turn_id,
        user_message=f"user:{turn_id}",
        assistant_response=f"assistant:{turn_id}",
        epoch=epoch,
        immediate=immediate,
    )


async def _wait_until(
    predicate,
    *,
    timeout_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition was not satisfied before timeout")
        await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_scheduler_flushes_at_turn_threshold_and_preserves_epoch() -> None:
    batches: list[AttentionBatch] = []
    config = _config(turn_threshold=3)

    async def processor(batch: AttentionBatch) -> bool:
        batches.append(batch)
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        config_poll_interval_seconds=0.005,
    )
    try:
        assert await scheduler.enqueue(_turn("turn-1", epoch=7)) is True
        assert await scheduler.enqueue(_turn("turn-2", epoch=8)) is True
        await asyncio.sleep(0.01)
        assert batches == []

        assert await scheduler.enqueue(_turn("turn-3", epoch=9)) is True
        assert await scheduler.wait_idle(timeout_seconds=1.0) is True

        assert [[turn.turn_id for turn in batch] for batch in batches] == [
            ["turn-1", "turn-2", "turn-3"]
        ]
        assert [turn.epoch for turn in batches[0]] == [7, 8, 9]
        assert await scheduler.enqueue(_turn("turn-2", epoch=8)) is False
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_deduplicates_and_serializes_new_turns_during_processing() -> None:
    config = _config(turn_threshold=1)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    batches: list[list[str]] = []
    active_by_session: defaultdict[str, int] = defaultdict(int)
    max_active_by_session: defaultdict[str, int] = defaultdict(int)

    async def processor(batch: AttentionBatch) -> bool:
        session_id = batch[0].session_id
        active_by_session[session_id] += 1
        max_active_by_session[session_id] = max(
            max_active_by_session[session_id],
            active_by_session[session_id],
        )
        batches.append([turn.turn_id for turn in batch])
        if batch[0].turn_id == "turn-1":
            first_started.set()
            await release_first.wait()
        active_by_session[session_id] -= 1
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        config_poll_interval_seconds=0.005,
    )
    try:
        assert await scheduler.enqueue(_turn("turn-1")) is True
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        assert await scheduler.enqueue(_turn("turn-1")) is False
        assert await scheduler.enqueue(_turn("turn-2")) is True
        await asyncio.sleep(0.01)
        assert batches == [["turn-1"]]

        release_first.set()
        assert await scheduler.wait_idle(timeout_seconds=1.0) is True

        assert batches == [["turn-1"], ["turn-2"]]
        assert max_active_by_session["session-1"] == 1
    finally:
        release_first.set()
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_processes_distinct_sessions_independently() -> None:
    config = _config(turn_threshold=1)
    both_started = asyncio.Event()
    release = asyncio.Event()
    active_sessions: set[str] = set()

    async def processor(batch: AttentionBatch) -> bool:
        active_sessions.add(batch[0].session_id)
        if len(active_sessions) == 2:
            both_started.set()
        await release.wait()
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        config_poll_interval_seconds=0.005,
    )
    try:
        await scheduler.enqueue(_turn("turn-1", session_id="session-1"))
        await scheduler.enqueue(_turn("turn-2", session_id="session-2"))

        await asyncio.wait_for(both_started.wait(), timeout=1.0)
        assert active_sessions == {"session-1", "session-2"}
        worker_tasks = [
            state.task
            for state in scheduler._states.values()
            if state.task is not None
        ]

        release.set()
        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        await _wait_until(lambda: scheduler._states == {})
        assert all(task.done() for task in worker_tasks)
    finally:
        release.set()
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_reloads_config_while_a_turn_is_waiting() -> None:
    config = _config(turn_threshold=20, idle_seconds=10.0, max_delay_seconds=20.0)
    batches: list[AttentionBatch] = []

    async def processor(batch: AttentionBatch) -> bool:
        batches.append(batch)
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: SimpleNamespace(l0=config),
        config_poll_interval_seconds=0.005,
    )
    try:
        await scheduler.enqueue(_turn("turn-1"))
        await asyncio.sleep(0.02)
        assert batches == []

        config.attention_update_idle_seconds = 0.01
        config.attention_update_max_delay_seconds = 1.0

        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert [[turn.turn_id for turn in batch] for batch in batches] == [["turn-1"]]
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_max_delay_is_not_extended_by_new_turns() -> None:
    config = _config(
        turn_threshold=20,
        idle_seconds=0.4,
        max_delay_seconds=0.5,
    )
    batches: list[AttentionBatch] = []

    async def processor(batch: AttentionBatch) -> bool:
        batches.append(batch)
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        config_poll_interval_seconds=0.005,
    )
    try:
        await scheduler.enqueue(_turn("turn-1"))
        await asyncio.sleep(0.1)
        await scheduler.enqueue(_turn("turn-2"))
        await asyncio.sleep(0.1)
        await scheduler.enqueue(_turn("turn-3"))

        assert await scheduler.wait_idle(timeout_seconds=0.36) is True
        assert [[turn.turn_id for turn in batch] for batch in batches] == [
            ["turn-1", "turn-2", "turn-3"]
        ]
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_immediate_turn_bypasses_all_batch_delays() -> None:
    config = _config(
        turn_threshold=20,
        idle_seconds=10.0,
        max_delay_seconds=20.0,
    )
    batches: list[AttentionBatch] = []

    async def processor(batch: AttentionBatch) -> bool:
        batches.append(batch)
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
    )
    try:
        await scheduler.enqueue(_turn("turn-urgent", immediate=True))

        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert [[turn.turn_id for turn in batch] for batch in batches] == [["turn-urgent"]]
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_failed_batch_is_retained_and_retried_with_backoff() -> None:
    config = _config(turn_threshold=1)
    attempts: list[tuple[float, list[str]]] = []

    async def processor(batch: AttentionBatch) -> bool:
        attempts.append((time.monotonic(), [turn.turn_id for turn in batch]))
        return len(attempts) >= 2

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        retry_initial_seconds=0.03,
        retry_max_seconds=0.03,
        config_poll_interval_seconds=0.002,
    )
    try:
        await scheduler.enqueue(_turn("turn-1"))

        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert [turn_ids for _, turn_ids in attempts] == [["turn-1"], ["turn-1"]]
        assert attempts[1][0] - attempts[0][0] >= 0.02
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_new_turn_joins_retained_batch_after_processor_failure() -> None:
    config = _config(turn_threshold=1)
    first_failed = asyncio.Event()
    attempts: list[list[str]] = []

    async def processor(batch: AttentionBatch) -> bool:
        attempts.append([turn.turn_id for turn in batch])
        if len(attempts) == 1:
            first_failed.set()
            return False
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        retry_initial_seconds=0.04,
        retry_max_seconds=0.04,
        config_poll_interval_seconds=0.002,
    )
    try:
        await scheduler.enqueue(_turn("turn-1"))
        await asyncio.wait_for(first_failed.wait(), timeout=1.0)
        await scheduler.enqueue(_turn("turn-2"))

        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert attempts == [["turn-1"], ["turn-1"], ["turn-2"]]
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_limits_batch_size_and_drains_all_pending_turns() -> None:
    config = _config(turn_threshold=1)
    attempts: list[list[str]] = []

    async def processor(batch: AttentionBatch) -> bool:
        attempts.append([turn.turn_id for turn in batch])
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        max_batch_turns=2,
        max_pending_turns_per_session=6,
        config_poll_interval_seconds=0.002,
    )
    try:
        for index in range(5):
            assert await scheduler.enqueue(_turn(f"turn-{index}")) is True

        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert attempts == [
            ["turn-0", "turn-1"],
            ["turn-2", "turn-3"],
            ["turn-4"],
        ]
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_drops_failed_prefix_after_attempt_limit_and_continues() -> None:
    config = _config(turn_threshold=1)
    attempts: list[list[str]] = []

    async def processor(batch: AttentionBatch) -> bool:
        turn_ids = [turn.turn_id for turn in batch]
        attempts.append(turn_ids)
        return turn_ids == ["turn-2"]

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        retry_initial_seconds=0.01,
        retry_max_seconds=0.01,
        config_poll_interval_seconds=0.002,
        max_batch_turns=1,
        max_batch_attempts=3,
    )
    try:
        assert await scheduler.enqueue(_turn("turn-1")) is True
        assert await scheduler.enqueue(_turn("turn-2")) is True

        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert attempts == [
            ["turn-1"],
            ["turn-1"],
            ["turn-1"],
            ["turn-2"],
        ]
        assert await scheduler.enqueue(_turn("turn-1")) is False
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_permanent_failure_drops_batch_and_becomes_idle(
    caplog,
) -> None:
    config = _config(turn_threshold=1)
    attempts = 0

    async def processor(batch: AttentionBatch) -> bool:
        nonlocal attempts
        attempts += 1
        return False

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        retry_initial_seconds=0.01,
        retry_max_seconds=0.01,
        config_poll_interval_seconds=0.002,
    )
    try:
        with caplog.at_level(logging.WARNING):
            assert await scheduler.enqueue(_turn("turn-1")) is True
            assert await scheduler.wait_idle(timeout_seconds=1.0) is True

        assert attempts == 3
        assert scheduler.has_pending_work() is False
        assert any("retry budget exhausted" in record.getMessage() for record in caplog.records)
    finally:
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_caps_pending_turns_and_keeps_newer_waiting_work() -> None:
    config = _config(turn_threshold=1)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    attempts: list[list[str]] = []

    async def processor(batch: AttentionBatch) -> bool:
        turn_ids = [turn.turn_id for turn in batch]
        attempts.append(turn_ids)
        if turn_ids == ["turn-1"]:
            first_started.set()
            await release_first.wait()
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        max_batch_turns=1,
        max_pending_turns_per_session=3,
        config_poll_interval_seconds=0.002,
    )
    try:
        assert await scheduler.enqueue(_turn("turn-1")) is True
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        assert await scheduler.enqueue(_turn("turn-2")) is True
        assert await scheduler.enqueue(_turn("turn-3")) is True
        assert await scheduler.enqueue(_turn("turn-4")) is True

        release_first.set()
        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert attempts == [["turn-1"], ["turn-3"], ["turn-4"]]
        assert await scheduler.enqueue(_turn("turn-2")) is False
    finally:
        release_first.set()
        await scheduler.shutdown(flush=False)


@pytest.mark.asyncio
async def test_scheduler_hard_caps_each_batch_at_twenty_turns() -> None:
    config = _config(
        turn_threshold=100,
        idle_seconds=10.0,
        max_delay_seconds=20.0,
    )
    attempts: list[list[str]] = []

    async def processor(batch: AttentionBatch) -> bool:
        attempts.append([turn.turn_id for turn in batch])
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        max_batch_turns=100,
        max_pending_turns_per_session=100,
    )
    for index in range(45):
        assert await scheduler.enqueue(_turn(f"turn-{index}")) is True

    assert await scheduler.shutdown(flush=True, timeout_seconds=1.0) is True
    assert [len(batch) for batch in attempts] == [20, 20, 5]


@pytest.mark.asyncio
async def test_shutdown_can_flush_pending_turns_and_closes_scheduler() -> None:
    config = _config(
        turn_threshold=20,
        idle_seconds=10.0,
        max_delay_seconds=20.0,
    )
    batches: list[AttentionBatch] = []

    async def processor(batch: AttentionBatch) -> bool:
        batches.append(batch)
        return True

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
    )
    await scheduler.enqueue(_turn("turn-1"))
    await scheduler.enqueue(_turn("turn-2"))

    assert await scheduler.shutdown(flush=True, timeout_seconds=1.0) is True
    assert [[turn.turn_id for turn in batch] for batch in batches] == [["turn-1", "turn-2"]]
    assert await scheduler.enqueue(_turn("turn-3")) is False


@pytest.mark.asyncio
async def test_shutdown_flush_retries_a_failed_forced_batch() -> None:
    config = _config(
        turn_threshold=20,
        idle_seconds=10.0,
        max_delay_seconds=20.0,
    )
    attempts: list[list[str]] = []

    async def processor(batch: AttentionBatch) -> bool:
        attempts.append([turn.turn_id for turn in batch])
        return len(attempts) >= 2

    scheduler = L0AttentionUpdateScheduler(
        processor=processor,
        config_getter=lambda: config,
        retry_initial_seconds=0.02,
        retry_max_seconds=0.02,
        config_poll_interval_seconds=0.002,
    )
    await scheduler.enqueue(_turn("turn-1"))

    assert await scheduler.shutdown(flush=True, timeout_seconds=1.0) is True
    assert attempts == [["turn-1"], ["turn-1"]]


@pytest.mark.parametrize(
    ("user_message", "incoming_fact_kind", "expected"),
    [
        ("普通聊聊今天的天气", "user_message", False),
        ("继续", "user_message", False),
        ("帮我把这个问题修一下", "user_message", False),
        ("不是新专，是新专辑", "user_message", True),
        ("更正一下：地点是上海，不是杭州。", "user_message", True),
        ("这个话题到此为止。", "user_message", True),
        ("以后讨论方案时，必须先说结论。", "user_message", True),
        ("I meant the desktop app, not the website.", "user_message", True),
        ("Let's stop discussing this topic.", "user_message", True),
        ("Going forward, always lead with the conclusion.", "user_message", True),
        ("ordinary worker result", "worker_update", True),
        ("ordinary explore result", "explore_task_completed", True),
    ],
)
def test_immediate_attention_update_detection_is_conservative(
    user_message: str,
    incoming_fact_kind: str,
    expected: bool,
) -> None:
    assert (
        should_update_attention_immediately(
            user_message=user_message,
            incoming_fact_kind=incoming_fact_kind,
        )
        is expected
    )
