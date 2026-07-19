"""TDD tests for Phase 2 cluster C (DelegationEventPort) and D (BackgroundPort).

Asserts that build_tool_capabilities() wires delegation_events and background
ports (not None) and that they expose the correct method names.
"""


def test_delegation_events_port_wired():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    assert caps.delegation_events is not None, "delegation_events port must be wired"
    assert hasattr(caps.delegation_events, "broadcast_event"), (
        "delegation_events must expose broadcast_event"
    )
    assert hasattr(caps.delegation_events, "broadcast_state"), (
        "delegation_events must expose broadcast_state"
    )
    assert caps.delegation_artifacts is not None
    assert hasattr(caps.delegation_artifacts, "register")
    reset_tool_capabilities()


def test_background_port_wired():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    assert caps.background is not None, "background port must be wired"
    assert hasattr(caps.background, "suspend_waiting_user"), (
        "background must expose suspend_waiting_user"
    )
    assert hasattr(caps.background, "resume_from_wait"), (
        "background must expose resume_from_wait"
    )
    reset_tool_capabilities()


def test_interaction_port_wired():
    """Phase 4 Task 1: ask-user capability is wired and exposes ``ask``."""
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    assert caps.interaction is not None, "interaction port must be wired"
    assert hasattr(caps.interaction, "ask"), "interaction must expose ask"
    reset_tool_capabilities()
