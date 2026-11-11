"""Bounded generation retries include rate limits and clear failed previews."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from magi.agent.execution.function_calling import llm
from magi.agent.execution.function_calling.llm_invocation import FunctionCallingLlmRequest
from magi.config.models import ThinkingDepth


class _Boom(Exception):
    pass


def _request():
    return FunctionCallingLlmRequest(
        "initial", "function_calling:chat_tools", "system", [], ThinkingDepth.NONE,
        None, None, None, "chat_agent", "chat", 1,
    )


def _prepared(delays=(1.0, 2.0, 4.0)):
    return llm._PreparedLlmCall(SimpleNamespace(_RATE_LIMIT_BACKOFF_SECONDS=delays), "initial", 0, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("message,status", [
    ("Error code: 429 - rate limit", None),
    ("您的账户已达到速率限制，请您控制请求频率", None),
    ("http error", 429),
])
async def test_rate_limit_classifications_drive_bounded_retry(monkeypatch, message, status):
    error = _Boom(message)
    if status is not None:
        error.status_code = status
    expected = {"result": "retried successfully"}
    invoke = AsyncMock(side_effect=[error, error, expected])
    sleep, budget, events = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    monkeypatch.setattr(llm, "reserve_task_llm_calls", budget)
    monkeypatch.setattr(llm, "emit_stream_event", events)
    assert await llm._call_with_generation_recovery(
        _prepared(), _request(), control=None, tools=[], invoke=invoke,
    ) is expected
    assert invoke.await_count == budget.await_count + 1 == 3
    assert sleep.await_args_list == [call(1.0), call(2.0)]
    assert [entry.args[0].kind for entry in events.await_args_list] == ["text_reset", "text_reset"]
    assert len({entry.args[0].request_id for entry in invoke.await_args_list}) == 3


@pytest.mark.asyncio
async def test_non_rate_limit_error_propagates_without_retry_or_delay(monkeypatch):
    error = _Boom("some other failure")
    invoke, sleep = AsyncMock(side_effect=error), AsyncMock()
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with pytest.raises(_Boom) as raised:
        await llm._call_with_generation_recovery(
            _prepared(), _request(), control=None, tools=[], invoke=invoke,
        )
    assert raised.value is error
    assert invoke.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_backoff_exhausts_budget():
    invoke = AsyncMock(side_effect=_Boom("429 Too Many Requests"))
    with pytest.raises(_Boom):
        await llm._call_with_generation_recovery(
            _prepared((0.0, 0.0)), _request(), control=None, tools=[], invoke=invoke,
        )
    assert invoke.await_count == 3
