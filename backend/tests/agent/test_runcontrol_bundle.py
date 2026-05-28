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
