"""Fixtures for SessionRunCoordinator tests."""
from __future__ import annotations

from magi.control.run_control import RunControl, null_run_control
from magi.chat.task_agent.run_store import SessionRunStore
from magi.chat.task_agent.session_run_coordinator import (
    SessionRunCoordinator,
)


def _build_coordinator(store: SessionRunStore) -> SessionRunCoordinator:
    """Construct a minimal SessionRunCoordinator backed by the given store.

    The the input queue is not exercised by request_retract tests
    so a default (rule-based) classifier is fine.
    """
    return SessionRunCoordinator(run_store=store)


def build_coordinator_without_active_run() -> tuple[SessionRunCoordinator, SessionRunStore]:
    store = SessionRunStore()
    coord = _build_coordinator(store)
    return coord, store


def build_coordinator_with_active_run(
    *, session_id: str
) -> tuple[SessionRunCoordinator, RunControl]:
    """Build a coordinator with an active run AND a registered RunControl
    for that run. Returns the coordinator + the control so the test can
    assert on the control's signals after request_retract."""
    store = SessionRunStore()
    active = store.create_active_run(session_id, root_turn_id="t1", root_user_message="hi")
    control = null_run_control()
    store.register_active_run_control(session_id, active.run_id, control)
    coord = _build_coordinator(store)
    return coord, control


def build_coordinator_with_active_run_no_control(*, session_id: str) -> SessionRunCoordinator:
    """Active run exists but no RunControl is registered (orphaned
    background-restored run scenario)."""
    store = SessionRunStore()
    store.create_active_run(session_id, root_turn_id="t1", root_user_message="hi")
    return _build_coordinator(store)
