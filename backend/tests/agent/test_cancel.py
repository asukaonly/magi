from __future__ import annotations

import asyncio

import pytest

from magi.agent.cancel import (
    CancelToken,
    EventCancelToken,
    NullCancelToken,
    SessionRunCancelToken,
    null_cancel_token,
)


def test_null_cancel_token_satisfies_protocol() -> None:
    token = NullCancelToken()
    assert isinstance(token, CancelToken)


@pytest.mark.asyncio
async def test_null_cancel_token_is_never_cancelled() -> None:
    token = NullCancelToken()
    assert await token.is_cancelled() is False
    assert token.reason is None


def test_null_cancel_token_singleton_is_reused() -> None:
    assert null_cancel_token() is null_cancel_token()


@pytest.mark.asyncio
async def test_event_cancel_token_starts_uncancelled() -> None:
    token = EventCancelToken()
    assert await token.is_cancelled() is False
    assert token.reason is None


@pytest.mark.asyncio
async def test_event_cancel_token_records_reason_and_sets_event() -> None:
    token = EventCancelToken()

    token.cancel(reason="user_interrupt")

    assert await token.is_cancelled() is True
    assert token.reason == "user_interrupt"


@pytest.mark.asyncio
async def test_event_cancel_token_is_idempotent() -> None:
    token = EventCancelToken()
    token.cancel(reason="first")
    token.cancel(reason="second")

    # First reason wins; later cancels are no-ops.
    assert token.reason == "first"
    assert await token.is_cancelled() is True


@pytest.mark.asyncio
async def test_event_cancel_token_wait_unblocks_on_cancel() -> None:
    token = EventCancelToken()

    async def _cancel_soon() -> None:
        await asyncio.sleep(0)
        token.cancel(reason="external")

    await asyncio.gather(token.wait(), _cancel_soon())
    assert await token.is_cancelled() is True
    assert token.reason == "external"


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
