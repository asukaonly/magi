"""Behavior tests for the task-agent fact queue boundary."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from magi.agent.runtime import task_agent
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import FactQueue
from magi.chat.task_agent import session_control


def _fact(name: str) -> FactRecord:
    return FactRecord(
        agent_id="chat:test",
        agent_type="chat",
        agent_instance_id="test",
        event_type=name,
        payload={"name": name},
    )


def test_fact_queue_exposes_ordered_peek_snapshot_and_filtering() -> None:
    queue = FactQueue(maxsize=3)
    first = _fact("first")
    second = _fact("second")
    third = _fact("third")

    queue.put_nowait(first)
    queue.put_nowait(second)
    queue.put_nowait(third)

    assert queue.full() is True
    assert queue.peek_nowait() is first
    assert queue.snapshot() == (first, second, third)
    assert queue.remove_if(lambda fact: fact is second) == (second,)
    assert queue.snapshot() == (first, third)
    assert queue.get_nowait() is first
    assert queue.get_nowait() is third
    assert queue.empty() is True

    with pytest.raises(asyncio.QueueEmpty):
        queue.peek_nowait()


def test_task_agent_consumers_do_not_read_queue_storage_directly() -> None:
    sources = (
        inspect.getsource(task_agent.TaskAgent),
        inspect.getsource(session_control.ChatSessionControlMixin),
    )

    assert all("._fact_queue._queue" not in source for source in sources)
