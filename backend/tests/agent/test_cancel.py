from __future__ import annotations

import asyncio

import pytest

from magi.agent.cancel import (
    EventCancelToken,
    NullCancelToken,
    SessionRunCancelToken,
)


@pytest.mark.asyncio
async def test_null_cancel_token_never_signals_its_waiter():
    token = NullCancelToken()
    waiter = asyncio.create_task(token.wait())
    try:
        await asyncio.sleep(0)
        assert await token.is_cancelled() is False
        assert token.reason is None
        assert not waiter.done()
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_event_cancel_token_wakes_waiter_once_and_keeps_original_reason():
    token = EventCancelToken()
    assert await token.is_cancelled() is False
    assert token.reason is None
    waiter = asyncio.create_task(token.wait())
    try:
        await asyncio.sleep(0)
        assert not waiter.done()
        token.cancel(reason="user_interrupt")
        token.cancel(reason="later_timeout")
        await asyncio.wait_for(waiter, timeout=1)
        assert await token.is_cancelled() is True
        assert token.reason == "user_interrupt"
        await asyncio.wait_for(token.wait(), timeout=1)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


class _FakeCoordinator:
    def __init__(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        status: str | None,
    ) -> None:
        self.session_id = session_id
        self.run_id = run_id
        self.revision = revision
        self.status = status

    def get_run_status(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> str | None:
        if session_id != self.session_id:
            return None
        if run_id is not None and run_id != self.run_id:
            return None
        if revision is not None and int(revision) != self.revision:
            return None
        return self.status


@pytest.mark.asyncio
async def test_session_run_cancel_token_cancelling_sets_reason() -> None:
    coordinator = _FakeCoordinator(
        session_id="s", run_id="r", revision=0, status="cancelling"
    )
    token = SessionRunCancelToken(
        coordinator=coordinator, session_id="s", run_id="r", revision=0
    )

    assert await token.is_cancelled() is True
    assert token.reason == "session_run_cancelling"


@pytest.mark.asyncio
async def test_session_run_cancel_token_ignores_mismatched_run() -> None:
    coordinator = _FakeCoordinator(
        session_id="s", run_id="r-other", revision=0, status="cancelling"
    )
    token = SessionRunCancelToken(
        coordinator=coordinator, session_id="s", run_id="r", revision=0
    )

    assert await token.is_cancelled() is False
    assert token.reason is None
