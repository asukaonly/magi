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
coordinator additionally appends an ``IncomingEvent(external_inbound)``
to ``active_run.pending_events`` so downstream consumers see the typed
signal (the legacy ``pending_turns`` append is kept too — Phase H Task 4
already made session_turn_queue read both queues).

The active-run tests use a ``_StubRunStore`` (matching the pattern from
``test_session_run_coordinator_dispatcher.py``) because the real
``SessionRunStore`` deepcopies on every ``get_active_run`` read — the
mutation site (``active_run.pending_events.append``) intentionally
targets the typed in-memory ``AgentRun`` object held by the active-run
registry, mirroring how ``dispatch_event`` writes pending events today.
"""

from __future__ import annotations

import pytest

from magi.agent.task_agents.handlers.run_contracts import AgentRun
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.agent.task_agents.common.contracts import UserMessagePayload
from magi.events.recall_feedback import RecallFeedbackKind


class _StubRunStore:
    """Minimal run-store stub for active-run pending_events assertions.

    Pattern mirrors ``_StubRunStore`` in
    ``test_session_run_coordinator_dispatcher.py``: ``get_active_run``
    returns the SAME ``AgentRun`` instance each call so callers can read
    back mutations to ``pending_events`` / ``pending_turns``.
    """

    def __init__(self):
        self._active: dict[str, AgentRun] = {}

    def set_active(self, session_id: str, run: AgentRun) -> None:
        self._active[session_id] = run

    def get_active_run(self, session_id: str):
        return self._active.get(session_id)

    def get_active_run_control(self, session_id: str, run_id: str):
        return None

    def append_pending_turn(
        self,
        session_id: str,
        turn_id: str,
        content: str,
        *,
        disposition: str = "augment",
    ):
        from magi.agent.task_agents.handlers.run_contracts import PendingTurn

        run = self._active[session_id]
        pt = PendingTurn(
            turn_id=turn_id,
            content=content,
            revision=run.revision,
            disposition=disposition,
        )
        run.pending_turns.append(pt)
        return pt


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


# === Active-run + external source → also IncomingEvent ===


def test_handle_user_turn_appends_incoming_event_for_external_source_with_active_run():
    """When a Telegram message arrives WHILE a run is active, an
    IncomingEvent(external_inbound) gets appended to pending_events.

    Uses ``_StubRunStore`` so ``get_active_run`` returns the SAME
    ``AgentRun`` instance — the real L0-backed store deepcopies, mirroring
    how ``dispatch_event`` exercises the same mutation point.
    """
    store = _StubRunStore()
    run = AgentRun(session_id="s-mix", run_id="r-mix")
    store.set_active("s-mix", run)
    coord = SessionRunCoordinator(run_store=store)

    second = UserMessagePayload(
        user_id="u-5",
        session_id="s-mix",
        content="from telegram",
        turn_id="turn-mix-2",
        source="telegram",
    )
    coord.handle_user_turn(second)

    inbound = [e for e in run.pending_events if e.event_type == "external_inbound"]
    assert len(inbound) == 1
    assert inbound[0].payload.get("source_channel") == "telegram"
    assert inbound[0].payload.get("content") == "from telegram"
    assert inbound[0].payload.get("user_id") == "u-5"
    # Sanity: legacy ``pending_turns`` queue still gets the entry too
    # (we DON'T replace it — Phase H Task 4 made the consumer read both).
    assert len(run.pending_turns) == 1


def test_handle_user_turn_no_incoming_event_for_api_source_with_active_run():
    """A second 'api' message into an active run should NOT add an
    IncomingEvent(external_inbound) — that's reserved for external sources."""
    store = _StubRunStore()
    run = AgentRun(session_id="s-api-only", run_id="r-api")
    store.set_active("s-api-only", run)
    coord = SessionRunCoordinator(run_store=store)

    second = UserMessagePayload(
        user_id="u-6",
        session_id="s-api-only",
        content="second",
        turn_id="turn-2",
        source="api",
    )
    coord.handle_user_turn(second)

    inbound = [e for e in run.pending_events if e.event_type == "external_inbound"]
    assert inbound == []


@pytest.mark.asyncio
async def test_ahandle_user_turn_appends_incoming_event_for_external_source_with_active_run():
    """Async path mirrors the sync behavior: external source on active
    run → IncomingEvent(external_inbound) appended."""
    store = _StubRunStore()
    run = AgentRun(session_id="s-mix-async", run_id="r-async")
    store.set_active("s-mix-async", run)
    coord = SessionRunCoordinator(run_store=store)

    payload = UserMessagePayload(
        user_id="u-7",
        session_id="s-mix-async",
        content="from weixin async",
        turn_id="turn-wx-async",
        source="weixin",
    )
    await coord.ahandle_user_turn(payload)

    inbound = [e for e in run.pending_events if e.event_type == "external_inbound"]
    assert len(inbound) == 1
    assert inbound[0].payload.get("source_channel") == "weixin"
    assert inbound[0].payload.get("content") == "from weixin async"
