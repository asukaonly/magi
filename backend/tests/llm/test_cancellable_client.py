"""Unit tests for CancellableLLMClient."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Iterable

import pytest

from magi.agent.cancel import EventCancelToken
from magi.agent.run_control import (
    RetractRequested,
    RetractSignal,
    null_run_control,
)
from magi.llm.cancellable_client import (
    CancellableLLMClient,
    CancellationRaised,
    RetractRaised,
)
from magi.llm.streaming_events import LLMStreamEvent


@dataclass
class _FakeBridgeResponse:
    content: str
    metadata: dict


class _FakeBridge:
    """Stub LLMProviderBridge that produces a configurable async stream."""

    def __init__(self, chunks: Iterable[str], delay_per_chunk: float = 0.0) -> None:
        self._chunks = list(chunks)
        self._delay = delay_per_chunk
        self.chat_response_calls = 0
        self.chat_response_stream_calls = 0

    async def chat_response(self, **kwargs) -> _FakeBridgeResponse:
        self.chat_response_calls += 1
        await asyncio.sleep(self._delay)
        return _FakeBridgeResponse(content="".join(self._chunks), metadata={})

    async def chat_response_stream(self, **kwargs) -> AsyncIterator[LLMStreamEvent]:
        self.chat_response_stream_calls += 1
        for chunk in self._chunks:
            await asyncio.sleep(self._delay)
            yield LLMStreamEvent(kind="text_delta", text=chunk)


@pytest.mark.asyncio
async def test_call_returns_content_when_no_control_signals_set() -> None:
    bridge = _FakeBridge(chunks=["hello ", "world"])
    client = CancellableLLMClient(bridge=bridge)
    control = null_run_control()

    result = await client.call(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        control=control,
    )

    assert result.content == "hello world"
    assert bridge.chat_response_calls == 1


@pytest.mark.asyncio
async def test_stream_yields_chunks_when_no_control_signals_set() -> None:
    bridge = _FakeBridge(chunks=["a", "b", "c"])
    client = CancellableLLMClient(bridge=bridge)
    control = null_run_control()

    collected: list[str] = []
    async for event in client.stream(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        control=control,
    ):
        if event.kind == "text_delta":
            collected.append(event.text or "")

    assert collected == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_stream_raises_cancellation_when_cancel_token_fires_mid_stream() -> None:
    bridge = _FakeBridge(chunks=["a", "b", "c"], delay_per_chunk=0.02)
    cancel = EventCancelToken()
    control = null_run_control()
    # Replace cancel_token field — RunControl is mutable.
    control.cancel_token = cancel
    client = CancellableLLMClient(bridge=bridge)

    async def trigger_cancel() -> None:
        await asyncio.sleep(0.025)
        cancel.cancel(reason="user_request")

    asyncio.create_task(trigger_cancel())

    collected: list[str] = []
    with pytest.raises(CancellationRaised):
        async for event in client.stream(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            control=control,
        ):
            if event.kind == "text_delta":
                collected.append(event.text or "")

    # We should have received at least one chunk before the cancel.
    assert len(collected) >= 1
    assert len(collected) < 3


@pytest.mark.asyncio
async def test_stream_raises_retract_when_retract_signal_fires_mid_stream() -> None:
    bridge = _FakeBridge(chunks=["a", "b", "c"], delay_per_chunk=0.02)
    retract = RetractSignal()
    control = null_run_control()
    control.retract_signal = retract
    client = CancellableLLMClient(bridge=bridge)

    async def trigger_retract() -> None:
        await asyncio.sleep(0.025)
        retract.request(RetractRequested(reason="user_retract"))

    asyncio.create_task(trigger_retract())

    with pytest.raises(RetractRaised) as excinfo:
        async for _event in client.stream(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            control=control,
        ):
            pass

    assert excinfo.value.payload.reason == "user_retract"


@pytest.mark.asyncio
async def test_call_non_streaming_checks_cancel_before_dispatch() -> None:
    """Non-streaming calls cannot poll mid-flight, so we at least check
    once before sending the request."""
    bridge = _FakeBridge(chunks=["resp"])
    cancel = EventCancelToken()
    cancel.cancel(reason="user_request")
    control = null_run_control()
    control.cancel_token = cancel
    client = CancellableLLMClient(bridge=bridge)

    with pytest.raises(CancellationRaised):
        await client.call(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            control=control,
        )

    assert bridge.chat_response_calls == 0


def test_cancellation_raised_with_none_reason_constructs_cleanly() -> None:
    exc = CancellationRaised(reason=None)
    assert "cancelled" in str(exc).lower()
    assert exc.reason is None


def test_retract_raised_with_none_payload_constructs_cleanly() -> None:
    exc = RetractRaised(payload=None)
    assert "retracted" in str(exc).lower()
    assert exc.payload is None
