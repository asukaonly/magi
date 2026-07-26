"""RunTrigger belongs to one live chat execution, not to L0."""

from __future__ import annotations

from magi_plugin_sdk.run_trigger import RunTrigger

from magi.chat.task_agent.run_store import SessionRunStore


def test_trigger_is_available_for_the_live_run() -> None:
    store = SessionRunStore()
    trigger = RunTrigger(
        trigger_type="external_inbound",
        source_channel="weixin",
        requester="user-1",
        priority="foreground",
        payload={"content": "你好"},
    )

    store.create_active_run(
        session_id="session-1",
        run_id="run-1",
        trigger=trigger,
    )

    active_run = store.get_active_run("session-1")
    assert active_run is not None
    assert active_run.trigger == trigger


def test_new_process_state_has_no_control_less_triggered_run() -> None:
    original = SessionRunStore()
    original.create_active_run(
        session_id="session-1",
        run_id="run-1",
        trigger=RunTrigger(
            trigger_type="external_inbound",
            source_channel="weixin",
            requester="user-1",
            priority="foreground",
        ),
    )

    restarted = SessionRunStore()

    assert restarted.get_active_run("session-1") is None
