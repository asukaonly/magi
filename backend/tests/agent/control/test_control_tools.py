"""Integration-ish tests for plan mode / todo / ask tools.

These tests install a real ``ControlSessionStore`` (and a real
``InteractionBroker`` for ask) into the runtime container, call the
tools directly, and assert their observable effects.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from magi.agent.control.common import InteractionBroker
from magi.agent.control.session_store import ControlSessionStore
from magi.core.container import get_container
from magi.tools.builtin.ask_user_question_tool import AskUserQuestionTool
from magi.tools.builtin.plan_mode_tool import EnterPlanModeTool, ExitPlanModeTool
from magi.tools.builtin.todo_write_tool import TodoWriteTool
from magi.tools.schema import ToolExecutionContext


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
        env_vars={"session_id": session_id, "intent": intent},
        permissions=[],
        enabled_features=[],
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
                "items": [
                    {"title": "a"},
                    {"title": "b", "status": "in_progress"},
                ]
            },
            _ctx("sid-B"),
        )
        assert result.success
        assert len(result.data["items"]) == 2
        titles = [t["title"] for t in result.data["items"]]
        assert titles == ["a", "b"]


@pytest.mark.asyncio
async def test_todo_write_rejects_double_in_progress() -> None:
    store = ControlSessionStore()
    with _override(control_session_store=store):
        tool = TodoWriteTool()
        result = await tool.execute(
            {
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
