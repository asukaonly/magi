"""Tests for background-task runtime notifications."""

from __future__ import annotations


import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskTriggerSource,
    broadcast_background_task_state_changed,
)
from magi.agent.background import notifications as notifications_module


class _FakeStore:
    def __init__(self) -> None:
        self.records = []

    async def append_notification(self, record) -> None:
        self.records.append(record)


def _make_task(status: BackgroundTaskStatus) -> BackgroundTask:
    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="t1",
        title="Demo",
        goal="g",
        selected_tools=[],
        trigger_source=BackgroundTaskTriggerSource.RULE,
    )
    task = BackgroundTask.new(spec)
    task.status = status
    task.summary = "done"
    return task


@pytest.mark.asyncio
async def test_broadcast_swallows_store_errors(monkeypatch):
    def _raise():
        raise RuntimeError("trace store offline")

    monkeypatch.setattr(notifications_module, "resolve_runtime_trace_store", _raise)
    # Must not raise.
    await broadcast_background_task_state_changed(_make_task(BackgroundTaskStatus.FAILED))


@pytest.mark.asyncio
async def test_broadcast_swallows_serialization_errors(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(notifications_module, "resolve_runtime_trace_store", lambda: store)

    class _Broken:
        spec = None

        def to_dict(self):
            raise ValueError("cannot serialize")

    await broadcast_background_task_state_changed(_Broken())
    assert store.records == []
