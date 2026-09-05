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


def test_user_message_payload_carries_source():
    p = UserMessagePayload(
        user_id="u1",
        session_id="s1",
        content="hi",
        source="telegram",
    )
    assert p.source == "telegram"


def test_user_message_payload_source_defaults_to_api():
    p = UserMessagePayload(user_id="u1", session_id="s1", content="hi")
    assert p.source == "api"


def test_user_message_payload_source_roundtrip():
    p = UserMessagePayload(
        user_id="u1",
        session_id="s1",
        content="hi",
        source="weixin",
    )
    d = p.to_dict()
    assert d["source"] == "weixin"
    p2 = UserMessagePayload.from_dict(d, fallback_user_id="u1")
    assert p2.source == "weixin"


def test_user_message_payload_source_missing_in_legacy_payload():
    """from_dict with no source key → default 'api' (backward compat)."""
    d = {"user_id": "u1", "session_id": "s1", "content": "hi"}
    p = UserMessagePayload.from_dict(d, fallback_user_id="u1")
    assert p.source == "api"


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


def test_handle_user_turn_creates_user_message_trigger_for_api_source():
    """For source='api' (HTTP /chat), trigger stays as user_message."""
    coord = SessionRunCoordinator()
    payload = UserMessagePayload(
        user_id="u-1",
        session_id="s-api",
        content="hello",
        turn_id="turn-api-1",
        source="api",
    )

    decision = coord.handle_user_turn(payload)

    assert decision.active_run is not None
    assert decision.active_run.trigger is not None
    assert decision.active_run.trigger.trigger_type == "user_message"
    assert decision.active_run.trigger.source_channel == "chat_sse"
    assert decision.active_run.trigger.requester == "u-1"
    assert decision.active_run.trigger.correlation == ["turn-api-1"]


def test_handle_user_turn_creates_external_inbound_trigger_for_telegram():
    """For source='telegram', trigger is external_inbound with
    source_channel='telegram'."""
    coord = SessionRunCoordinator()
    payload = UserMessagePayload(
        user_id="u-2",
        session_id="s-tg",
        content="hello from tg",
        turn_id="turn-tg-1",
        source="telegram",
    )

    decision = coord.handle_user_turn(payload)

    assert decision.active_run is not None
    assert decision.active_run.trigger is not None
    assert decision.active_run.trigger.trigger_type == "external_inbound"
    assert decision.active_run.trigger.source_channel == "telegram"
    assert decision.active_run.trigger.requester == "u-2"
    assert decision.active_run.trigger.correlation == ["turn-tg-1"]
    assert decision.active_run.trigger.payload.get("content") == "hello from tg"


def test_handle_user_turn_creates_external_inbound_trigger_for_weixin():
    """Same for weixin."""
    coord = SessionRunCoordinator()
    payload = UserMessagePayload(
        user_id="u-3",
        session_id="s-wx",
        content="ni hao",
        turn_id="turn-wx-1",
        source="weixin",
    )

    decision = coord.handle_user_turn(payload)

    assert decision.active_run is not None
    assert decision.active_run.trigger is not None
    assert decision.active_run.trigger.trigger_type == "external_inbound"
    assert decision.active_run.trigger.source_channel == "weixin"


def test_handle_user_turn_user_message_for_empty_source_string():
    """Empty/whitespace source treated as 'api' for backward compat."""
    coord = SessionRunCoordinator()
    payload = UserMessagePayload(
        user_id="u-4",
        session_id="s-empty",
        content="hi",
        turn_id="turn-empty",
        source="",
    )

    decision = coord.handle_user_turn(payload)

    assert decision.active_run is not None
    assert decision.active_run.trigger is not None
    assert decision.active_run.trigger.trigger_type == "user_message"


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
