"""Integration: SessionRunCoordinator.request_retract fires the active
run's RunControl.retract_signal so external 'retract button' UI actions
can target an in-flight chat run."""
from __future__ import annotations

import inspect


from magi.control.run_control import (
    RetractRequested,
    null_run_control,
)


def test_coordinator_exposes_request_retract() -> None:
    from magi.chat.task_agent.session_run_coordinator import (
        SessionRunCoordinator,
    )

    assert hasattr(SessionRunCoordinator, "request_retract")
    sig = inspect.signature(SessionRunCoordinator.request_retract)
    assert "session_id" in sig.parameters


def test_store_exposes_run_control_register_lookup_unregister() -> None:
    from magi.chat.task_agent.run_store import SessionRunStore

    assert hasattr(SessionRunStore, "register_active_run_control")
    assert hasattr(SessionRunStore, "get_active_run_control")
    assert hasattr(SessionRunStore, "unregister_active_run_control")


def test_store_register_lookup_unregister_roundtrip() -> None:
    """Registering a RunControl makes it retrievable by (session_id, run_id);
    unregistering removes it."""
    from magi.chat.task_agent.run_store import SessionRunStore

    store = SessionRunStore()
    control = null_run_control()

    store.register_active_run_control("session_a", "run_1", control)
    assert store.get_active_run_control("session_a", "run_1") is control

    store.unregister_active_run_control("session_a", "run_1")
    assert store.get_active_run_control("session_a", "run_1") is None


def test_store_unregister_missing_is_noop() -> None:
    """unregister_active_run_control should not raise if no control is registered."""
    from magi.chat.task_agent.run_store import SessionRunStore

    store = SessionRunStore()
    # No registration yet — should be safe to unregister.
    store.unregister_active_run_control("nonexistent_session", "nonexistent_run")


def test_request_retract_returns_false_when_no_active_run() -> None:
    """request_retract on a session with no active run is a no-op returning False."""
    from agent.fixtures_session_run_coordinator import (
        build_coordinator_without_active_run,
    )

    coordinator, _store = build_coordinator_without_active_run()
    result = coordinator.request_retract(session_id="nonexistent")
    assert result is False


def test_request_retract_sets_signal_on_active_run_control() -> None:
    """request_retract must locate the live RunControl associated with
    the session's active run and call retract_signal.request(payload)."""
    from agent.fixtures_session_run_coordinator import (
        build_coordinator_with_active_run,
    )

    coordinator, control = build_coordinator_with_active_run(session_id="s1")

    result = coordinator.request_retract(
        session_id="s1",
        payload=RetractRequested(reason="user_retract", note="oops"),
    )

    assert result is True
    assert control.retract_signal.is_requested()
    payload = control.retract_signal.payload
    assert payload is not None
    assert payload.note == "oops"


def test_request_retract_returns_false_when_active_run_has_no_registered_control() -> None:
    """If the store has an active run but no associated control (e.g.,
    background-restored run), request_retract returns False rather than
    raising."""
    from agent.fixtures_session_run_coordinator import (
        build_coordinator_with_active_run_no_control,
    )

    coordinator = build_coordinator_with_active_run_no_control(session_id="s_orphan")
    result = coordinator.request_retract(session_id="s_orphan")
    assert result is False
