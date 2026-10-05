"""Unit tests for the in-loop 429 backoff helper on
``FunctionCallingOrchestrator``.
"""

from __future__ import annotations


import pytest

from magi.agent.execution.function_calling import FunctionCallingOrchestrator


class _Boom(Exception):
    pass


def _make_orchestrator() -> FunctionCallingOrchestrator:
    orch = FunctionCallingOrchestrator.__new__(FunctionCallingOrchestrator)
    return orch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,status",
    [
        ("Error code: 429 - rate limit", None),
        ("您的账户已达到速率限制，请您控制请求频率", None),
        ("http error", 429),
    ],
)
async def test_rate_limit_classifications_drive_bounded_retry(monkeypatch, message, status):
    from unittest.mock import AsyncMock, call

    orchestrator = _make_orchestrator()
    monkeypatch.setattr(orchestrator, "_RATE_LIMIT_BACKOFF_SECONDS", (1.0, 2.0, 4.0), raising=False)
    error = _Boom(message)
    if status is not None:
        error.status_code = status
    expected = {"result": "retried successfully"}
    invoke = AsyncMock(side_effect=[error, error, expected])
    sleep = AsyncMock()
    monkeypatch.setattr("magi.agent.execution.function_calling.failures.asyncio.sleep", sleep)
    assert await orchestrator._invoke_with_rate_limit_backoff(invoke, label="test") is expected
    assert invoke.await_count == 3
    assert sleep.await_args_list == [call(1.0), call(2.0)]


@pytest.mark.asyncio
async def test_non_rate_limit_error_propagates_without_retry_or_delay(monkeypatch):
    from unittest.mock import AsyncMock

    orchestrator = _make_orchestrator()
    error = _Boom("some other failure")
    invoke = AsyncMock(side_effect=error)
    sleep = AsyncMock()
    monkeypatch.setattr("magi.agent.execution.function_calling.failures.asyncio.sleep", sleep)
    with pytest.raises(_Boom) as raised:
        await orchestrator._invoke_with_rate_limit_backoff(invoke, label="test")
    assert raised.value is error
    invoke.assert_awaited_once_with()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_backoff_exhausts_budget(monkeypatch):
    orch = _make_orchestrator()
    monkeypatch.setattr(
        FunctionCallingOrchestrator,
        "_RATE_LIMIT_BACKOFF_SECONDS",
        (0.0, 0.0),
    )

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise _Boom("429 Too Many Requests")

    with pytest.raises(_Boom):
        await orch._invoke_with_rate_limit_backoff(factory, label="test")
    # initial + 2 backoff retries
    assert calls["n"] == 3
