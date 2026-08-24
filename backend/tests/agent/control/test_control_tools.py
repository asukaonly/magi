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
from magi_plugin_sdk.capabilities import ToolCapabilities


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
async def test_enter_plan_mode_sets_state() -> None:
    store = ControlSessionStore()
    with _override(control_session_store=store):
        tool = EnterPlanModeTool()
        result = await tool.execute({}, _ctx("sid-A"))
        assert result.success
        assert result.data["active"] is True
        assert store.plan_state("sid-A").active is True


@pytest.mark.asyncio
async def test_exit_plan_mode_requires_plan_text() -> None:
    store = ControlSessionStore()
    with _override(control_session_store=store):
        tool = ExitPlanModeTool()
        bad = await tool.execute({"plan": "   "}, _ctx("sid-A"))
        assert not bad.success
        ok = await tool.execute({"plan": "step 1\nstep 2"}, _ctx("sid-A"))
        assert ok.success
        assert store.plan_state("sid-A").plan_text == "step 1\nstep 2"


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
async def test_todo_write_happy_path() -> None:
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
                ]
            },
            _ctx("sid-B"),
        )
        assert result.success
        assert len(result.data["items"]) == 2
        titles = [t["content"] for t in result.data["items"]]
        assert titles == ["a", "b"]


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
                ]
            },
            _ctx("sid-B"),
        )
        assert not result.success
        assert "in_progress" in (result.error or "")


@pytest.mark.asyncio
async def test_ask_user_question_resolves_via_broker() -> None:
    store = ControlSessionStore()
    broker = InteractionBroker()
    with _override(
        control_session_store=store,
        control_interaction_broker=broker,
    ):
        tool = AskUserQuestionTool()

        async def answer_later() -> None:
            # Wait until the ask is registered, then resolve.
            for _ in range(50):
                ask = store.ask_state("sid-C")
                if ask is not None:
                    await broker.resolve(
                        interaction_id=ask.request_id,
                        kind="ask",
                        response="yes",
                    )
                    return
                await asyncio.sleep(0.01)

        answerer = asyncio.create_task(answer_later())
        result = await tool.execute(
            {"question": "Proceed?", "options": ["yes", "no"], "timeout_seconds": 5},
            _ctx("sid-C"),
        )
        await answerer
        assert result.success
        assert result.data == {"answer": "yes"}
        closed = store.ask_state("sid-C")
        assert closed is not None
        assert closed.resolution == "user"
        assert closed.answer == "yes"


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
async def test_enter_plan_mode_publishes_plan_state_event() -> None:
    store = ControlSessionStore()
    bus = _RecordingBus()
    with _override(control_session_store=store, message_bus=bus):
        result = await EnterPlanModeTool().execute({}, _ctx("sid-A"))
        assert result.success
    plan_events = [e for e in bus.events if e.type == EventTypes.CONTROL_PLAN_STATE_CHANGED]
    assert len(plan_events) == 1
    payload = plan_events[0].data
    assert payload.session_id == "sid-A"
    assert payload.state["active"] is True


@pytest.mark.asyncio
async def test_exit_plan_mode_publishes_plan_state_event() -> None:
    store = ControlSessionStore()
    bus = _RecordingBus()
    with _override(control_session_store=store, message_bus=bus):
        result = await ExitPlanModeTool().execute({"plan": "step 1\nstep 2"}, _ctx("sid-A"))
        assert result.success
    plan_events = [e for e in bus.events if e.type == EventTypes.CONTROL_PLAN_STATE_CHANGED]
    assert len(plan_events) == 1
    assert plan_events[0].data.state["active"] is False


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
                    await broker.resolve(
                        interaction_id=ask.request_id, kind="ask", response="yes"
                    )
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
