"""Unit tests for RunControl bundle: RetractSignal, SuspendSignal, RunControl."""
from __future__ import annotations

import asyncio

import pytest

from magi.agent.run_control import (
    RetractRequested,
    RetractSignal,
)


@pytest.mark.asyncio
async def test_retract_signal_is_not_requested_initially() -> None:
    signal = RetractSignal()
    assert not signal.is_requested()
    assert signal.payload is None


@pytest.mark.asyncio
async def test_retract_signal_records_payload_on_request() -> None:
    signal = RetractSignal()
    payload = RetractRequested(reason="user_retract", requested_by="user", note="oops")

    signal.request(payload)

    assert signal.is_requested()
    assert signal.payload == payload


@pytest.mark.asyncio
async def test_retract_signal_is_idempotent_keeps_first_payload() -> None:
    signal = RetractSignal()
    first = RetractRequested(reason="user_retract", note="first")
    second = RetractRequested(reason="cascade", note="second")

    signal.request(first)
    signal.request(second)

    assert signal.payload == first


@pytest.mark.asyncio
async def test_retract_signal_wait_unblocks_after_request() -> None:
    signal = RetractSignal()

    async def requester() -> None:
        await asyncio.sleep(0.01)
        signal.request(RetractRequested(reason="user_retract"))

    asyncio.create_task(requester())
    payload = await signal.wait()
    assert payload.reason == "user_retract"


@pytest.mark.asyncio
async def test_retract_signal_request_with_no_arg_uses_default_payload() -> None:
    signal = RetractSignal()
    signal.request()  # no payload supplied
    assert signal.is_requested()
    assert signal.payload == RetractRequested()
    assert signal.payload.reason == "user_retract"


from magi.agent.run_control import (  # noqa: E402
    SuspendRequested,
    SuspendSignal,
)


@pytest.mark.asyncio
async def test_suspend_signal_starts_not_requested() -> None:
    signal = SuspendSignal()
    assert not signal.is_requested()
    assert signal.payload is None


@pytest.mark.asyncio
async def test_suspend_signal_records_payload() -> None:
    signal = SuspendSignal()
    payload = SuspendRequested(reason="window_closed", requested_by="ui_layer")

    signal.request(payload)

    assert signal.is_requested()
    assert signal.payload == payload


@pytest.mark.asyncio
async def test_suspend_signal_can_be_cleared_for_resume() -> None:
    """Unlike RetractSignal, SuspendSignal can be cleared so the same run
    object survives a suspend/resume cycle without rebuilding."""
    signal = SuspendSignal()
    signal.request(SuspendRequested(reason="window_closed"))
    assert signal.is_requested()

    signal.clear()

    assert not signal.is_requested()
    assert signal.payload is None


@pytest.mark.asyncio
async def test_suspend_signal_request_with_no_arg_uses_default_payload() -> None:
    signal = SuspendSignal()
    signal.request()
    assert signal.is_requested()
    assert signal.payload == SuspendRequested()
    assert signal.payload.reason == "window_closed"


@pytest.mark.asyncio
async def test_suspend_signal_wait_unblocks_after_request() -> None:
    signal = SuspendSignal()

    async def requester() -> None:
        await asyncio.sleep(0.01)
        signal.request(SuspendRequested(reason="window_closed"))

    asyncio.create_task(requester())
    payload = await signal.wait()
    assert payload.reason == "window_closed"


@pytest.mark.asyncio
async def test_suspend_signal_is_idempotent_keeps_first_payload() -> None:
    signal = SuspendSignal()
    first = SuspendRequested(reason="window_closed", note="first")
    second = SuspendRequested(reason="explicit_pause", note="second")

    signal.request(first)
    signal.request(second)

    assert signal.payload == first


@pytest.mark.asyncio
async def test_suspend_signal_clear_then_request_accepts_new_payload() -> None:
    """After clear(), a subsequent request() must be honored (the
    idempotency guard only applies while the signal is set)."""
    signal = SuspendSignal()
    first = SuspendRequested(reason="window_closed", note="first")
    second = SuspendRequested(reason="explicit_pause", note="second")

    signal.request(first)
    assert signal.payload == first

    signal.clear()
    signal.request(second)

    assert signal.is_requested()
    assert signal.payload == second
