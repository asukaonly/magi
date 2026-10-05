from types import SimpleNamespace
from unittest.mock import Mock
import pytest

@pytest.mark.parametrize(
    "snapshot,activities", [(None, {}), ({"trace_id": "trace-canary"}, {"turn-3": {"tools": 2}})]
)
def test_trace_port_forwards_scope_and_preserves_missing_or_present_results(
    monkeypatch, snapshot, activities
):
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities
    from magi.api import services

    reader = SimpleNamespace(
        get_trace_snapshot=Mock(return_value=snapshot),
        get_turn_activity_map=Mock(return_value=activities),
    )
    monkeypatch.setattr(services, "get_chat_trace_read_service", lambda: reader)
    reset_tool_capabilities()
    try:
        trace = build_tool_capabilities().trace
        assert (
            trace.get_trace_snapshot(user_id="user-1", session_id="session-2", turn_id="turn-3")
            is snapshot
        )
        assert trace.get_turn_activity_map(user_id="user-1", session_id="session-2") is activities
        reader.get_trace_snapshot.assert_called_once_with(
            user_id="user-1", session_id="session-2", turn_id="turn-3"
        )
        reader.get_turn_activity_map.assert_called_once_with(
            user_id="user-1", session_id="session-2"
        )
    finally:
        reset_tool_capabilities()
