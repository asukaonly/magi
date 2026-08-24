"""Tests for ``publish_control_event``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from magi.control.common import events as events_module
from magi.runtime_trace.contracts import RuntimeNotificationRecord


@dataclass
class _FakeStore:
    records: list[RuntimeNotificationRecord] = field(default_factory=list)

    async def append_notification(
        self, record: RuntimeNotificationRecord
    ) -> int:
        self.records.append(record)
        return len(self.records)


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    store = _FakeStore()
    monkeypatch.setattr(
        events_module,
        "resolve_runtime_trace_store",
        lambda: store,
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

    monkeypatch.setattr(events_module, "resolve_runtime_trace_store", _raise)

    # Must not raise even when trace store cannot be resolved.
    await events_module.publish_control_event(
        "control.ask.requested",
        {"session_id": "sid-3", "request_id": "ask-3"},
        session_id="sid-3",
    )
