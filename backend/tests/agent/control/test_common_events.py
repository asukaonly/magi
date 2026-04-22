"""Tests for ``publish_control_event``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from magi.agent.control.common import events as events_module
from magi.core import runtime_bindings
from magi.runtime_trace.contracts import RuntimeNotificationRecord


@dataclass
class _FakeStore:
    records: list[RuntimeNotificationRecord] = field(default_factory=list)

    async def append_notification(
        self, record: RuntimeNotificationRecord
    ) -> int:
        self.records.append(record)
        return len(self.records)


class _FakeContainer:
    """Container-shaped object exposing `.runtime_trace_store()`."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def runtime_trace_store(self) -> Any:
        return self._store


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    store = _FakeStore()
    monkeypatch.setattr(
        runtime_bindings,
        "get_container",
        lambda: _FakeContainer(store),
    )
    return store


@pytest.mark.asyncio
async def test_publish_control_event_records_notification(
    fake_store: _FakeStore,
) -> None:
    await events_module.publish_control_event(
        "control.permission.requested",
        {"request_id": "req-1", "session_id": "sid-1", "tool": "send_message"},
        session_id="sid-1",
        user_id="u1",
    )
    assert len(fake_store.records) == 1
    rec = fake_store.records[0]
    assert rec.channel == "control.permission.requested"
    assert rec.session_id == "sid-1"
    assert rec.user_id == "u1"
    payload = json.loads(rec.payload_json)
    assert payload["request_id"] == "req-1"
    assert payload["tool"] == "send_message"
    assert rec.created_at_ms > 0


@pytest.mark.asyncio
async def test_publish_control_event_swallows_store_errors(
    fake_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(record: RuntimeNotificationRecord) -> int:
        raise RuntimeError("disk full")

    monkeypatch.setattr(fake_store, "append_notification", _boom)

    # Must not raise.
    await events_module.publish_control_event(
        "control.ask.requested",
        {"request_id": "ask-1"},
        session_id="sid-2",
    )


@pytest.mark.asyncio
async def test_publish_control_event_tolerates_missing_trace_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> Any:
        raise RuntimeError("no container")

    monkeypatch.setattr(runtime_bindings, "get_container", _raise)

    # Must not raise even when trace store cannot be resolved.
    await events_module.publish_control_event(
        "control.todo.updated",
        {"session_id": "sid-3", "items": []},
        session_id="sid-3",
    )
