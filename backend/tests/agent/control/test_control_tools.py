"""Integration-ish tests for plan mode / todo / ask tools.

These tests install a real ``ControlSessionStore`` (and a real
``InteractionBroker`` for ask) into the runtime container, call the
tools directly, and assert their observable effects.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from magi.control.common import InteractionBroker
from magi.control.session_store import ControlSessionStore
from magi.core.container import get_container
from magi.events.events import EventTypes
from magi.tools.builtin.ask_user_question_tool import AskUserQuestionTool
from magi.control.tools import EnterPlanModeTool, ExitPlanModeTool, TodoWriteTool
from magi.bootstrap.tool_capabilities import _HostInteractionPort
from magi.tools.schema import ToolExecutionContext
from magi.core.tool_capabilities import ToolCapabilities


class _RecordingBus:
    """Capture control state-change events published by the actuator tools."""

    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> bool:
        self.events.append(event)
        return True

    def types(self) -> list[str]:
        return [e.type for e in self.events]


@contextlib.contextmanager
def _override(**bindings):
    container = get_container()
    providers = {k: getattr(container, k) for k in bindings}
    for key, value in bindings.items():
        providers[key].override(value)
    try:
        yield container
    finally:
        for key in bindings:
            providers[key].reset_override()


def _ctx(session_id: str = "sid", intent: str = "chat") -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="test-agent",
        env_vars={"session_id": session_id, "run_id": "run-1", "intent": intent},
        permissions=[],
        enabled_features=[],
        # ask_user_question routes through the SDK InteractionPort; the host
        # adapter resolves the overridden control bindings installed below.
        capabilities=ToolCapabilities(interaction=_HostInteractionPort()),
    )


@pytest.mark.asyncio
async def test_plan_mode_tool_without_session_fails() -> None:
    store = ControlSessionStore()
    with _override(control_session_store=store):
        tool = EnterPlanModeTool()
        ctx = ToolExecutionContext(
            agent_id="test-agent",
            env_vars={},
            permissions=[],
            enabled_features=[],
        )
        result = await tool.execute({}, ctx)
        assert not result.success


@pytest.mark.asyncio
async def test_todo_write_updates_canonical_plan_and_rejects_invalid_mutation() -> None:
    store = ControlSessionStore()
    with _override(control_session_store=store):
        tool = TodoWriteTool()
        result = await tool.execute(
            {
                "expected_version": 0,
                "required": True,
                "items": [
                    {"title": "a"},
                    {"title": "b", "status": "in_progress"},
                ],
            },
            _ctx("sid-B"),
        )
        assert result.success
        assert len(result.data["items"]) == 2
        titles = [t["content"] for t in result.data["items"]]
        assert titles == ["a", "b"]

        plan = store.current_run_plan("sid-B", run_id="run-1")
        assert plan is not None
        assert plan.to_dict() == result.data
        assert plan.version == 1
        assert plan.required is True
        assert [item.status.value for item in plan.items] == ["pending", "in_progress"]
        assert store.current_run_plan("other", run_id="run-1") is None
        assert store.current_run_plan("sid-B", run_id="other") is None

        before = plan.to_dict()
        invalid = await tool.execute(
            {
                "plan_id": plan.plan_id,
                "expected_version": plan.version,
                "items": [{"id": plan.items[0].id, "status": "in_progress"}],
            },
            _ctx("sid-B"),
        )
        assert not invalid.success
        assert "in_progress" in invalid.error
        assert store.current_run_plan("sid-B", run_id="run-1").to_dict() == before


@pytest.mark.asyncio
async def test_todo_write_rejects_double_in_progress() -> None:
    store = ControlSessionStore()
    with _override(control_session_store=store):
        tool = TodoWriteTool()
        result = await tool.execute(
            {
                "expected_version": 0,
                "items": [
                    {"title": "a", "status": "in_progress"},
                    {"title": "b", "status": "in_progress"},
                ],
            },
            _ctx("sid-B"),
        )
        assert not result.success
        assert "in_progress" in (result.error or "")
    assert store.current_run_plan("sid-B", run_id="run-1") is None


@pytest.mark.asyncio
async def test_ask_user_question_times_out() -> None:
    store = ControlSessionStore()
    broker = InteractionBroker()
    with _override(
        control_session_store=store,
        control_interaction_broker=broker,
    ):
        tool = AskUserQuestionTool()
        result = await tool.execute(
            {"question": "Proceed?", "timeout_seconds": 1},
            _ctx("sid-D"),
        )
        assert not result.success
        assert "no answer" in (result.error or "").lower()
        closed = store.ask_state("sid-D")
        assert closed is not None and closed.resolution == "timeout"


@pytest.mark.asyncio
async def test_ask_user_question_refuses_background_by_default() -> None:
    store = ControlSessionStore()
    broker = InteractionBroker()
    with _override(
        control_session_store=store,
        control_interaction_broker=broker,
    ):
        tool = AskUserQuestionTool()
        ctx = ToolExecutionContext(
            agent_id="test-agent",
            env_vars={"session_id": "sid-E", "intent": "background_scheduler"},
            permissions=[],
            enabled_features=[],
        )
        result = await tool.execute({"question": "Proceed?"}, ctx)
        assert not result.success
        assert "background" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_ask_user_question_suspends_and_resumes_background_task() -> None:
    """When invoked from a background run with the opt-in flag set,
    the tool must call the BackgroundTaskManager suspend/resume
    transitions around the broker wait, using the bg_task_id parsed
    from ``ToolExecutionContext.agent_id``.
    """
    store = ControlSessionStore()
    broker = InteractionBroker()

    class _RecordingManager:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def suspend_waiting_user(
            self, task_id: str, *, reason: str = "awaiting_user_answer"
        ) -> bool:
            self.calls.append(("suspend", task_id))
            return True

        async def resume_from_wait(self, task_id: str) -> bool:
            self.calls.append(("resume", task_id))
            return True

    manager = _RecordingManager()

    with _override(
        control_session_store=store,
        control_interaction_broker=broker,
    ):
        tool = AskUserQuestionTool()
        ctx = ToolExecutionContext(
            agent_id="background:bg_42",
            env_vars={"session_id": "sid-F", "intent": "background"},
            permissions=[],
            enabled_features=["allow_ask_in_background"],
            capabilities=ToolCapabilities(
                background=manager, interaction=_HostInteractionPort()
            ),
        )

        async def answer_later() -> None:
            for _ in range(50):
                ask = store.ask_state("sid-F")
                if ask is not None:
                    await broker.resolve(
                        interaction_id=ask.request_id,
                        kind="ask",
                        response="ok",
                    )
                    return
                await asyncio.sleep(0.01)

        answerer = asyncio.create_task(answer_later())
        result = await tool.execute(
            {"question": "Continue?", "timeout_seconds": 5}, ctx
        )
        await answerer
        assert result.success
        assert manager.calls == [
            ("suspend", "bg_42"),
            ("resume", "bg_42"),
        ]


@pytest.mark.asyncio
async def test_ask_user_question_resumes_background_on_timeout() -> None:
    store = ControlSessionStore()
    broker = InteractionBroker()

    class _RecordingManager:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def suspend_waiting_user(
            self, task_id: str, *, reason: str = "awaiting_user_answer"
        ) -> bool:
            self.calls.append(("suspend", task_id))
            return True

        async def resume_from_wait(self, task_id: str) -> bool:
            self.calls.append(("resume", task_id))
            return True

    manager = _RecordingManager()
    with _override(
        control_session_store=store,
        control_interaction_broker=broker,
    ):
        tool = AskUserQuestionTool()
        ctx = ToolExecutionContext(
            agent_id="background:bg_77",
            env_vars={"session_id": "sid-G", "intent": "background"},
            permissions=[],
            enabled_features=["allow_ask_in_background"],
            capabilities=ToolCapabilities(
                background=manager, interaction=_HostInteractionPort()
            ),
        )
        result = await tool.execute(
            {"question": "Continue?", "timeout_seconds": 1}, ctx
        )
        assert not result.success
        assert manager.calls == [
            ("suspend", "bg_77"),
            ("resume", "bg_77"),
        ]


# ---------------------------------------------------------------------------
# Control-Plane Extraction Phase 1: tools publish control state-change events
# (consumed by the chat-side ControlTranscriptSubscriber) instead of calling
# the former ``persist_*`` helpers directly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_mode_journey_persists_state_and_publishes_events():
    store = ControlSessionStore()
    bus = _RecordingBus()
    with _override(control_session_store=store, message_bus=bus):
        entered = await EnterPlanModeTool().execute({}, _ctx("sid-A"))
        assert entered.success
        assert entered.data["active"] is True
        assert store.plan_state("sid-A").active is True
        assert store.plan_state("other").active is False
        events = [e for e in bus.events if e.type == EventTypes.CONTROL_PLAN_STATE_CHANGED]
        assert len(events) == 1
        assert events[0].data.session_id == "sid-A"
        assert events[0].data.state["active"] is True

        bad = await ExitPlanModeTool().execute({"plan": "   "}, _ctx("sid-A"))
        assert not bad.success
        assert store.plan_state("sid-A").active is True
        assert len([e for e in bus.events if e.type == EventTypes.CONTROL_PLAN_STATE_CHANGED]) == 1

        exited = await ExitPlanModeTool().execute({"plan": "step 1\nstep 2"}, _ctx("sid-A"))
        assert exited.success
        state = store.plan_state("sid-A")
        assert state.active is False
        assert state.plan_text == "step 1\nstep 2"
    events = [e for e in bus.events if e.type == EventTypes.CONTROL_PLAN_STATE_CHANGED]
    assert len(events) == 2
    assert events[1].data.session_id == "sid-A"
    assert events[1].data.state["active"] is False
    assert events[1].data.state["plan_text"] == "step 1\nstep 2"


@pytest.mark.asyncio
async def test_ask_user_question_publishes_ask_events() -> None:
    store = ControlSessionStore()
    broker = InteractionBroker()
    bus = _RecordingBus()
    with _override(
        control_session_store=store,
        control_interaction_broker=broker,
        message_bus=bus,
    ):
        tool = AskUserQuestionTool()

        async def answer_later() -> None:
            for _ in range(50):
                ask = store.ask_state("sid-C")
                if ask is not None:
                    await broker.resolve(interaction_id=ask.request_id, kind="ask", response="yes")
                    return
                await asyncio.sleep(0.01)

        answerer = asyncio.create_task(answer_later())
        result = await tool.execute(
            {"question": "Proceed?", "options": ["yes", "no"], "timeout_seconds": 5},
            _ctx("sid-C"),
        )
        await answerer
        assert result.success

    types = bus.types()
    # Opening publishes a request event; answering publishes an answered event.
    assert EventTypes.CONTROL_ASK_REQUESTED in types
    assert EventTypes.CONTROL_ASK_ANSWERED in types
    answered = [e for e in bus.events if e.type == EventTypes.CONTROL_ASK_ANSWERED]
    assert answered[-1].data.answer == "yes"

    assert result.data == {"answer": "yes"}
    closed = store.ask_state("sid-C")
    assert closed is not None
    assert closed.resolution == "user"
    assert closed.answer == "yes"
    assert broker.pending_count() == 0
