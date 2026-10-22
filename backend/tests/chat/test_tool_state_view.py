"""Prompt cache boundaries are session-local and independent of trace storage."""

from magi.chat.task_agent.tool_state_view import ChatToolStateView


def test_tool_state_view_keeps_recent_bounded_records_and_normalizes_handles():
    view = ChatToolStateView()
    for index in range(105):
        view.record("user::session", {
            "tool_name": "photo_resolver", "status": "success", "turn_id": str(index),
            "execution_time_ms": 42.4, "result_summary": "Resolved one photo",
            "result_data": {"asset_ref_id": "asset-1"},
        })
    state = view.recent_state("user::session", limit=200)
    assert len(state) == 100
    assert [row["turn_id"] for row in state] == [str(index) for index in range(104, 4, -1)]
    assert state[0] == {
        "tool_name": "photo_resolver", "status": "success", "turn_id": "104",
        "execution_time_ms": 42, "outcome": "Resolved one photo", "handles": ["asset_ref_id:asset-1"],
    }
    assert view.recent_state("other::session") == []
    assert ChatToolStateView().recent_state("user::session") == []


def test_error_cache_clear_and_eviction_do_not_cross_sessions():
    view = ChatToolStateView()
    record = {"tool_name": "light", "status": "error", "error_code": "OFFLINE",
        "error_message": "Device is unavailable", "result_data": {"next_action": "Check connection"}}
    view.record("phone", record)
    view.record("desktop", record)
    assert view.recent_errors("phone")[0]["next_action"] == "Check connection"
    view.clear("phone")
    assert view.recent_errors("phone") == []
    assert len(view.recent_errors("desktop")) == 1
    view.evict("desktop")
    assert view.recent_state("desktop") == []
