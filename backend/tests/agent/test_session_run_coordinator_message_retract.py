"""Phase F Task 11: cross-run message retract.

``SessionRunCoordinator.request_message_retract`` is distinct from the
existing ``request_retract`` (which cancels the active run). It marks
ONE specific message redacted in the conversation log, then asks the
log for the list of runs that consumed it and fires RetractSignal on
each active dependent run.
"""
from __future__ import annotations

import pytest

from magi.agent.run_control import RunControl, null_run_control
from magi.chat.task_agent.run_store import SessionRunStore
from magi.chat.task_agent.session_run_coordinator import (
    SessionRunCoordinator,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingLog:
    """Captures append + find_dependents calls for assertions."""

    def __init__(self, *, dependents=None) -> None:
        self._dependents = list(dependents or [])
        self.appends: list[tuple] = []
        self.find_calls: list[tuple[str, str]] = []

    async def append(self, event, *, session_id: str) -> None:
        self.appends.append((event, session_id))

    async def find_dependents(
        self, *, session_id: str, message_id: str,
    ) -> list[tuple[str, int]]:
        self.find_calls.append((session_id, message_id))
        return list(self._dependents)


class _RaisingAppendLog(_RecordingLog):
    async def append(self, event, *, session_id: str) -> None:
        raise RuntimeError("storage offline")


class _RaisingFindLog(_RecordingLog):
    async def find_dependents(self, *, session_id, message_id):
        raise RuntimeError("query failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coord_with_runs(
    *,
    session_id: str,
    active_run_id: str,
    conversation_log,
    extra_controls: dict[str, RunControl] | None = None,
):
    """Build a coordinator with one active run + optional extra registered controls.

    ``extra_controls`` lets a test register multiple RunControls for the same
    session even though only one run is "active" — this mirrors the production
    case where ``find_dependents`` may return BOTH the currently active run AND
    historical run_ids that are still registered (e.g., a multi-run scenario).
    """
    store = SessionRunStore()
    active = store.create_active_run(
        session_id, root_turn_id="t1", root_user_message="hi",
    )
    # Force the active run to the requested run_id so tests are deterministic.
    active.run_id = active_run_id
    store.register_active_run_control(session_id, active_run_id, null_run_control())
    for run_id, control in (extra_controls or {}).items():
        store.register_active_run_control(session_id, run_id, control)
    coord = SessionRunCoordinator(
        run_store=store, conversation_log=conversation_log,
    )
    return coord


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_message_retract_appends_redaction_event() -> None:
    """Calling request_message_retract must append a message_redacted
    event to the log, referencing the target message_id."""
    log = _RecordingLog(dependents=[])
    coord = _coord_with_runs(
        session_id="s1", active_run_id="r1", conversation_log=log,
    )
    await coord.request_message_retract(session_id="s1", message_id="m1")
    assert len(log.appends) == 1
    event, session_id = log.appends[0]
    assert session_id == "s1"
    assert event.event_type == "message_redacted"
    assert event.redacts == "m1"


@pytest.mark.asyncio
async def test_request_message_retract_signals_dependent_active_runs() -> None:
    """When find_dependents returns active runs, their RetractSignal must
    be fired."""
    # r1 is the active run; both r1 and r2 are registered controls.
    r1_control = null_run_control()
    r2_control = null_run_control()
    log = _RecordingLog(dependents=[("r1", 0), ("r2", 0)])
    coord = _coord_with_runs(
        session_id="s1",
        active_run_id="r1",
        conversation_log=log,
        extra_controls={"r2": r2_control},
    )
    # Replace r1's null control with our trackable one so we can assert.
    coord._run_store.register_active_run_control("s1", "r1", r1_control)

    result = await coord.request_message_retract(session_id="s1", message_id="m1")
    assert result is True

    assert r1_control.retract_signal.is_requested()
    assert r2_control.retract_signal.is_requested()


@pytest.mark.asyncio
async def test_request_message_retract_skips_unregistered_dependents() -> None:
    """find_dependents may return run_ids that have no live RunControl
    (completed runs whose control was unregistered). Those are silently
    skipped — no exception, no signal."""
    r1_control = null_run_control()
    log = _RecordingLog(dependents=[("r1", 0), ("unknown-run", 0)])
    coord = _coord_with_runs(
        session_id="s1", active_run_id="r1", conversation_log=log,
    )
    coord._run_store.register_active_run_control("s1", "r1", r1_control)

    result = await coord.request_message_retract(session_id="s1", message_id="m1")
    # r1 got signaled; unknown-run silently skipped.
    assert result is True
    assert r1_control.retract_signal.is_requested()


@pytest.mark.asyncio
async def test_request_message_retract_returns_false_when_no_dependents() -> None:
    """No dependent runs → nothing to signal, returns False, but the
    redaction event STILL gets appended."""
    log = _RecordingLog(dependents=[])
    coord = _coord_with_runs(
        session_id="s1", active_run_id="r1", conversation_log=log,
    )
    result = await coord.request_message_retract(session_id="s1", message_id="m1")
    assert result is False
    # Redaction event was still appended.
    assert len(log.appends) == 1


@pytest.mark.asyncio
async def test_request_message_retract_returns_false_when_no_log() -> None:
    """Without a wired ConversationLog there's no place to look up
    dependents — call is a no-op returning False."""
    store = SessionRunStore()
    coord = SessionRunCoordinator(
        run_store=store, conversation_log=None,
    )
    result = await coord.request_message_retract(session_id="s1", message_id="m1")
    assert result is False


@pytest.mark.asyncio
async def test_request_message_retract_swallows_append_failure() -> None:
    """A failing log.append must not raise; the call returns False without
    proceeding to find_dependents."""
    log = _RaisingAppendLog(dependents=[("r1", 0)])
    coord = _coord_with_runs(
        session_id="s1", active_run_id="r1", conversation_log=log,
    )
    result = await coord.request_message_retract(session_id="s1", message_id="m1")
    assert result is False
    # find_dependents was NOT called — we bailed out at the append failure.
    assert log.find_calls == []


@pytest.mark.asyncio
async def test_request_message_retract_swallows_find_dependents_failure() -> None:
    """A failing find_dependents must not raise; redaction event is still
    appended, but no runs are signaled."""
    log = _RaisingFindLog(dependents=[("r1", 0)])
    coord = _coord_with_runs(
        session_id="s1", active_run_id="r1", conversation_log=log,
    )
    result = await coord.request_message_retract(session_id="s1", message_id="m1")
    assert result is False
    # The append still happened.
    assert len(log.appends) == 1
