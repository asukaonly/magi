"""Phase H+1: external inbound (telegram/weixin) gets RunTrigger(external_inbound).

These tests pin the wiring that propagates the dispatcher ``source`` field
through ``UserMessagePayload`` and into the ``RunTrigger`` attached to a
fresh ``AgentRun`` via ``SessionRunCoordinator.handle_user_turn``.

Sources that are MAGI-NATIVE (``api`` / ``chat_sse`` / ``magi-chat``) keep
the legacy Phase H Task 6 behavior (``trigger_type='user_message'``,
``source_channel='chat_sse'``). Every other source (telegram, weixin,
slack, ...) flips the run trigger to ``external_inbound`` with the
incoming source as ``source_channel``.

When an external message arrives while a run is already active, the
coordinator uses the same canonical ``pending_turns`` store as native chat.
The durable delivery envelope retains the source for restart redrive; the
live run uses one process-local queue for admitted pending user turns.
"""

from __future__ import annotations

import pytest

from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.agent.task_agents.common.contracts import UserMessagePayload
from magi.events.recall_feedback import RecallFeedbackKind


# === UserMessagePayload.source ===


def test_user_message_payload_parses_recall_feedback_from_command_metadata():
    payload = UserMessagePayload.from_dict(
        {
            "user_id": "u1",
            "session_id": "s1",
            "content": "Leave this out.",
            "metadata": {
                "recall_feedback": {
                    "kind": "item_irrelevant",
                    "target_message_id": "assistant-1",
                    "finding_ref": "event:event-1",
                }
            },
        },
        fallback_user_id="u1",
    )

    assert payload.recall_feedback is not None
    assert payload.recall_feedback.kind == RecallFeedbackKind.ITEM_IRRELEVANT
    assert payload.to_dict()["recall_feedback"] == {
        "kind": "item_irrelevant",
        "target_message_id": "assistant-1",
        "finding_ref": "event:event-1",
    }


# === handle_user_turn behavior — source-aware RunTrigger ===


@pytest.mark.parametrize(
    "source,expected_type,expected_channel",
    [
        (None, "user_message", "chat_sse"),
        ("api", "user_message", "chat_sse"),
        ("chat_sse", "user_message", "chat_sse"),
        ("magi-chat", "user_message", "chat_sse"),
        ("", "user_message", "chat_sse"),
        ("   ", "user_message", "chat_sse"),
        ("Telegram", "external_inbound", "telegram"),
        ("weixin", "external_inbound", "weixin"),
    ],
)
def test_fresh_run_preserves_parsed_source_in_live_trigger(source, expected_type, expected_channel):
    from magi_plugin_sdk.run_trigger import RunTrigger

    wire = {"user_id": "u-1", "session_id": "session-1", "content": "hello", "turn_id": "turn-1"}
    if source is not None:
        wire["source"] = source
    payload = UserMessagePayload.from_dict(wire, fallback_user_id="fallback")
    expected_source = source or "api"
    assert payload.source == expected_source
    restored = UserMessagePayload.from_dict(payload.to_dict(), fallback_user_id="fallback")
    assert restored.source == payload.source
    coordinator = SessionRunCoordinator()
    decision = coordinator.handle_user_turn(restored)
    assert decision.active_run is not None
    expected = RunTrigger(
        trigger_type=expected_type,
        source_channel=expected_channel,
        requester="u-1",
        priority="foreground",
        correlation=["turn-1"],
        payload={"content": "hello"},
    )
    assert decision.active_run.trigger == expected
    live = coordinator.get_active_run("session-1")
    assert live is not None
    assert live.run_id == decision.active_run.run_id
    assert live.trigger == expected


# === Active-run external input uses the canonical pending-turn store ===


def test_handle_user_turn_stores_external_followup_in_real_run_store():
    coord = SessionRunCoordinator()
    coord.handle_user_turn(
        UserMessagePayload(
            user_id="u-5",
            session_id="s-mix",
            content="root",
            turn_id="turn-mix-1",
            source="api",
        )
    )

    second = UserMessagePayload(
        user_id="u-5",
        session_id="s-mix",
        content="from telegram",
        turn_id="turn-mix-2",
        source="telegram",
    )
    decision = coord.handle_user_turn(second)
    run = coord.get_active_run("s-mix")

    assert run is not None
    assert [(turn.turn_id, turn.content) for turn in run.pending_turns] == [
        ("turn-mix-2", "from telegram")
    ]
    assert decision.latest_payload.source == "telegram"
    assert not hasattr(run, "pending_events")


@pytest.mark.asyncio
async def test_ahandle_user_turn_stores_external_followup_in_real_run_store():
    coord = SessionRunCoordinator()
    coord.handle_user_turn(
        UserMessagePayload(
            user_id="u-7",
            session_id="s-mix-async",
            content="root",
            turn_id="turn-root-async",
            source="api",
        )
    )

    payload = UserMessagePayload(
        user_id="u-7",
        session_id="s-mix-async",
        content="from weixin async",
        turn_id="turn-wx-async",
        source="weixin",
    )
    decision = await coord.ahandle_user_turn(payload)
    run = coord.get_active_run("s-mix-async")

    assert run is not None
    assert [(turn.turn_id, turn.content) for turn in run.pending_turns] == [
        ("turn-wx-async", "from weixin async")
    ]
    assert decision.latest_payload.source == "weixin"
