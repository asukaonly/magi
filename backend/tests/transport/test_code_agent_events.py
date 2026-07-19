"""Tests for code_agent delegation broadcasters."""
from __future__ import annotations

import json

import pytest

from magi.tools.code_agent.contracts import RunEvent
from magi.transport import code_agent_events as module
from magi.transport.code_agent_events import (
    broadcast_delegation_event,
    broadcast_delegation_state,
)


class _FakeStore:
    def __init__(self) -> None:
        self.records: list[object] = []

    async def append_notification(self, record) -> None:
        self.records.append(record)


@pytest.fixture(autouse=True)
def _reset_rate_limit() -> None:
    module._LAST_EMIT_MS.clear()
    yield
    module._LAST_EMIT_MS.clear()


@pytest.mark.asyncio
async def test_broadcast_event_writes_notification(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(module, "resolve_runtime_trace_store", lambda: store)
    await broadcast_delegation_event(
        user_id="u1", session_id="s1", turn_id="t1", delegation_id="d1",
        event=RunEvent(kind="status", ts_ms=1, payload={"hello": "world"}),
    )
    assert len(store.records) == 1
    record = store.records[0]
    assert record.channel == "code_agent_delegation_event"
    assert record.user_id == "u1"
    assert record.session_id == "s1"
    payload = json.loads(record.payload_json)
    assert payload["delegation_id"] == "d1"
    assert payload["turn_id"] == "t1"
    assert payload["event"]["kind"] == "status"


@pytest.mark.asyncio
async def test_broadcast_event_rate_limits_per_delegation(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(module, "resolve_runtime_trace_store", lambda: store)
    ev = RunEvent(kind="status", ts_ms=1, payload={})
    await broadcast_delegation_event(
        user_id="u", session_id="s", turn_id="t", delegation_id="dA", event=ev,
    )
    await broadcast_delegation_event(
        user_id="u", session_id="s", turn_id="t", delegation_id="dA", event=ev,
    )
    # second one rate-limited
    assert len(store.records) == 1
    # different delegation_id is not rate-limited
    await broadcast_delegation_event(
        user_id="u", session_id="s", turn_id="t", delegation_id="dB", event=ev,
    )
    assert len(store.records) == 2


@pytest.mark.asyncio
async def test_broadcast_state_never_rate_limited(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(module, "resolve_runtime_trace_store", lambda: store)
    for state in ("started", "running", "finished"):
        await broadcast_delegation_state(
            user_id="u", session_id="s", turn_id="t", delegation_id="dX",
            state=state, summary={"step": state},
        )
    assert len(store.records) == 3


@pytest.mark.asyncio
async def test_broadcast_state_clears_rate_limit_on_terminal(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(module, "resolve_runtime_trace_store", lambda: store)
    ev = RunEvent(kind="status", ts_ms=1, payload={})
    await broadcast_delegation_event(
        user_id="u", session_id="s", turn_id="t", delegation_id="dY", event=ev,
    )
    await broadcast_delegation_state(
        user_id="u", session_id="s", turn_id="t", delegation_id="dY",
        state="finished",
    )
    # Even though it's within 100 ms, the next event broadcast fires because
    # 'finished' cleared the rate-limit bucket.
    await broadcast_delegation_event(
        user_id="u", session_id="s", turn_id="t", delegation_id="dY", event=ev,
    )
    channels = [r.channel for r in store.records]
    assert channels == [
        "code_agent_delegation_event",
        "code_agent_delegation_state",
        "code_agent_delegation_event",
    ]


@pytest.mark.asyncio
async def test_broadcast_silent_when_ids_missing(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(module, "resolve_runtime_trace_store", lambda: store)
    await broadcast_delegation_event(
        user_id="", session_id="s", turn_id="t", delegation_id="d",
        event=RunEvent(kind="status", ts_ms=1, payload={}),
    )
    await broadcast_delegation_state(
        user_id="u", session_id="", turn_id="t", delegation_id="d",
        state="started",
    )
    assert store.records == []
