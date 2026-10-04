"""Cooperative signal lifecycles through the run-control bundle."""

from __future__ import annotations
import asyncio
import pytest
from magi.control.run_control import RetractRequested, SuspendRequested, null_run_control


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["retract", "suspend"])
@pytest.mark.parametrize("explicit", [False, True], ids=["default-payload", "explicit-payload"])
async def test_signal_waiters_observe_first_request_and_suspend_can_resume(kind, explicit):
    control = null_run_control()
    signal = getattr(control, f"{kind}_signal")
    payload_type = RetractRequested if kind == "retract" else SuspendRequested
    first = (
        payload_type(
            reason="user_retract" if kind == "retract" else "window_closed",
            requested_by="ui_layer",
            note="first",
        )
        if explicit
        else payload_type()
    )
    second = payload_type(
        reason="cascade" if kind == "retract" else "explicit_pause",
        requested_by="runtime",
        note="second",
    )
    assert not signal.is_requested()
    assert signal.payload is None
    waiter = asyncio.create_task(signal.wait())
    try:
        await asyncio.sleep(0)
        assert not waiter.done()
        if explicit:
            signal.request(first)
        else:
            signal.request()
        signal.request(second)
        assert await asyncio.wait_for(waiter, 1) == first
        assert signal.is_requested()
        assert signal.payload == first
        assert await asyncio.wait_for(signal.wait(), 1) == first
        if kind == "suspend":
            signal.clear()
            assert not signal.is_requested()
            assert signal.payload is None
            waiter = asyncio.create_task(signal.wait())
            await asyncio.sleep(0)
            assert not waiter.done()
            signal.request(second)
            assert await asyncio.wait_for(waiter, 1) == second
            assert signal.is_requested()
            assert signal.payload == second
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_default_bundle_starts_without_pending_control_requests():
    control = null_run_control()
    assert not await control.cancel_token.is_cancelled()
    assert not control.detach_signal.is_requested()
    assert not control.retract_signal.is_requested()
    assert not control.suspend_signal.is_requested()
    assert control.input_queue.is_empty()
