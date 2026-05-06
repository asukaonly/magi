import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from magi.agent.cancel import EventCancelToken
from magi.tools.builtin import ask_user_question_tool as ask_module
from magi.tools.builtin.ask_user_question_tool import AskUserQuestionTool
from magi.tools.schema import ToolExecutionContext


@dataclass(slots=True)
class _FakeAsk:
    request_id: str


class _FakeStore:
    def __init__(self) -> None:
        self.closed: tuple[str, str | None, str] | None = None

    async def open_ask(
        self,
        session_id: str,
        *,
        question: str,
        options: list[str],
        allow_free_text: bool,
        timeout_seconds: float,
        request_id: str | None,
    ) -> _FakeAsk:
        _ = (session_id, question, options, allow_free_text, timeout_seconds)
        return _FakeAsk(request_id=request_id or "ask-1")

    async def close_ask(
        self,
        session_id: str,
        *,
        answer: str | None,
        resolution: str,
    ) -> None:
        self.closed = (session_id, answer, resolution)


class _FakeBroker:
    async def wait(
        self,
        *,
        interaction_id: str,
        kind: str,
        timeout_seconds: float,
    ) -> Any:
        _ = (interaction_id, kind, timeout_seconds)
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_ask_user_question_closes_when_run_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _FakeStore()
    token = EventCancelToken()
    monkeypatch.setattr(ask_module, "resolve_control_session_store", lambda: store)
    monkeypatch.setattr(ask_module, "resolve_control_interaction_broker", _FakeBroker)

    async def cancel_soon() -> None:
        await asyncio.sleep(0)
        token.cancel("test_cancel")

    asyncio.create_task(cancel_soon())
    result = await AskUserQuestionTool().execute(
        {
            "question": "Continue?",
            "timeout_seconds": 30,
        },
        ToolExecutionContext(
            agent_id="chat",
            env_vars={"session_id": "session-1", "turn_id": "turn-1"},
            cancellation=token,
        ),
    )

    assert result.success is False
    assert result.error_code == "CANCELLED"
    assert store.closed == ("session-1", None, "cancelled")
