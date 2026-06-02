"""Phase H Task 5: SessionRunCoordinator.dispatch_event unified dispatcher."""
from __future__ import annotations

import pytest

from magi.agent.task_agents.handlers.run_contracts import AgentRun
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi_plugin_sdk.run_trigger import IncomingEvent


class _StubRunStore:
    """Minimal stub providing the run-store surface dispatch_event needs."""

    def __init__(self):
        self._active: dict[str, AgentRun] = {}

    def get_active_run(self, session_id: str):
        return self._active.get(session_id)

    def get_active_run_control(self, session_id: str, run_id: str):
        return None

    def set_active(self, session_id: str, run: AgentRun):
        self._active[session_id] = run


def _build_coordinator(*, run_store=None, conversation_log=None):
    """Minimal SessionRunCoordinator for unit-testing dispatch_event.

    Pattern mirrors fixtures_session_run_coordinator._build_coordinator:
    only ``run_store`` is needed for the basic surface; other deps are
    left at their defaults so dispatch_event can be exercised in isolation.
    """
    return SessionRunCoordinator(
        run_store=run_store if run_store is not None else _StubRunStore(),
        conversation_log=conversation_log,
    )


@pytest.mark.asyncio
async def test_dispatch_user_steer_appends_to_pending_events():
    store = _StubRunStore()
    run = AgentRun(session_id="s1", run_id="r1")
    store.set_active("s1", run)
    coord = _build_coordinator(run_store=store)
    event = IncomingEvent(
        event_id="e1",
        event_type="user_steer",
        target_run_id="r1",
        arrived_at_ms=100,
        payload={"content": "wait"},
    )
    handled = await coord.dispatch_event(session_id="s1", event=event)
    assert handled is True
    assert any(e.event_id == "e1" for e in run.pending_events)


@pytest.mark.asyncio
async def test_dispatch_user_steer_returns_false_when_no_active_run():
    store = _StubRunStore()  # nothing active
    coord = _build_coordinator(run_store=store)
    event = IncomingEvent(
        event_id="e1", event_type="user_steer",
        target_run_id=None, arrived_at_ms=100, payload={"content": "x"},
    )
    handled = await coord.dispatch_event(session_id="s1", event=event)
    assert handled is False


@pytest.mark.asyncio
async def test_dispatch_user_retract_invokes_do_message_retract():
    """Phase H Task 7: dispatch_event(user_retract) calls the shared
    private ``_do_message_retract`` (not the public wrapper) so the same
    logic is reachable from both entry points without recursion risk."""
    coord = _build_coordinator()
    captured = []

    async def _stub_do_retract(*, session_id, message_id, **kw):
        captured.append((session_id, message_id))
        return True

    coord._do_message_retract = _stub_do_retract
    event = IncomingEvent(
        event_id="e1", event_type="user_retract",
        target_run_id="r1", arrived_at_ms=100,
        payload={"message_id": "m1"},
    )
    handled = await coord.dispatch_event(session_id="s1", event=event)
    assert handled is True
    assert captured == [("s1", "m1")]


@pytest.mark.asyncio
async def test_dispatch_user_retract_returns_false_when_payload_missing_message_id():
    coord = _build_coordinator()
    event = IncomingEvent(
        event_id="e1", event_type="user_retract",
        target_run_id="r1", arrived_at_ms=100,
        payload={},  # no message_id
    )
    handled = await coord.dispatch_event(session_id="s1", event=event)
    assert handled is False


@pytest.mark.asyncio
async def test_dispatch_external_inbound_appends_to_pending_events_when_active_run_exists():
    store = _StubRunStore()
    run = AgentRun(session_id="s1", run_id="r1")
    store.set_active("s1", run)
    coord = _build_coordinator(run_store=store)
    event = IncomingEvent(
        event_id="e1", event_type="external_inbound",
        target_run_id=None, arrived_at_ms=100,
        payload={"text": "from telegram"},
    )
    handled = await coord.dispatch_event(session_id="s1", event=event)
    assert handled is True
    assert any(e.event_type == "external_inbound" for e in run.pending_events)


@pytest.mark.asyncio
async def test_dispatch_external_inbound_returns_false_when_no_active_run():
    """Caller (e.g. ChatTaskAgent) should start a new run with
    trigger=external_inbound when dispatch returns False."""
    store = _StubRunStore()
    coord = _build_coordinator(run_store=store)
    event = IncomingEvent(
        event_id="e1", event_type="external_inbound",
        target_run_id=None, arrived_at_ms=100,
        payload={"text": "from telegram"},
    )
    handled = await coord.dispatch_event(session_id="s1", event=event)
    assert handled is False


@pytest.mark.asyncio
async def test_request_message_retract_goes_through_internal_do_retract():
    """Phase H Task 7: ``request_message_retract`` is now a wrapper that
    funnels into the same private ``_do_message_retract`` used by
    ``dispatch_event(user_retract)``. Both paths share one implementation."""
    coord = _build_coordinator()
    captured = []

    async def _stub_do_retract(*, session_id, message_id, actor=None, payload=None):
        captured.append((session_id, message_id))
        return True

    coord._do_message_retract = _stub_do_retract

    # Both paths funnel into _do_message_retract:
    handled1 = await coord.request_message_retract(
        session_id="s1", message_id="m1",
    )
    handled2 = await coord.dispatch_event(
        session_id="s1",
        event=IncomingEvent(
            event_id="e1", event_type="user_retract",
            target_run_id="r1", arrived_at_ms=100,
            payload={"message_id": "m2"},
        ),
    )
    assert handled1 is True
    assert handled2 is True
    assert captured == [("s1", "m1"), ("s1", "m2")]
