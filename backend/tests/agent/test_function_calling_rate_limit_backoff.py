"""Unit tests for the in-loop 429 backoff helper on
``FunctionCallingOrchestrator``.
"""

from __future__ import annotations

import asyncio

import pytest

from magi.agent.execution.function_calling import FunctionCallingOrchestrator


class _Boom(Exception):
    pass


def _make_orchestrator() -> FunctionCallingOrchestrator:
    orch = FunctionCallingOrchestrator.__new__(FunctionCallingOrchestrator)
    return orch


@pytest.mark.asyncio
async def test_rate_limit_backoff_retries_and_succeeds(monkeypatch):
    orch = _make_orchestrator()
    monkeypatch.setattr(
        FunctionCallingOrchestrator,
        "_RATE_LIMIT_BACKOFF_SECONDS",
        (0.0, 0.0, 0.0),
    )

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Boom("Error code: 429 - rate limit")
        return "ok"

    result = await orch._invoke_with_rate_limit_backoff(factory, label="test")
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_rate_limit_backoff_reraises_non_rate_limit(monkeypatch):
    orch = _make_orchestrator()
    monkeypatch.setattr(
        FunctionCallingOrchestrator,
        "_RATE_LIMIT_BACKOFF_SECONDS",
        (0.0, 0.0, 0.0),
    )

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise _Boom("some other failure")

    with pytest.raises(_Boom):
        await orch._invoke_with_rate_limit_backoff(factory, label="test")
    assert calls["n"] == 1


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


@pytest.mark.asyncio
async def test_rate_limit_detector_chinese_message():
    assert FunctionCallingOrchestrator._is_rate_limit_exception(
        _Boom("您的账户已达到速率限制，请您控制请求频率")
    )


@pytest.mark.asyncio
async def test_rate_limit_detector_status_code_attr():
    class _ExcWithStatus(Exception):
        def __init__(self):
            super().__init__("http error")
            self.status_code = 429

    assert FunctionCallingOrchestrator._is_rate_limit_exception(_ExcWithStatus())


@pytest.mark.asyncio
async def test_rate_limit_detector_plain_error_is_not_rate_limit():
    assert not FunctionCallingOrchestrator._is_rate_limit_exception(
        _Boom("some other error")
    )


def test_asyncio_is_usable():
    # Smoke test to confirm the module still imports asyncio (required by
    # _invoke_with_rate_limit_backoff).
    assert asyncio.iscoroutinefunction(
        FunctionCallingOrchestrator._invoke_with_rate_limit_backoff
    )
