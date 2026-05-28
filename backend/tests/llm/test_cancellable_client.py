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
    """Stub LLMProviderBridge that produces a configurable async stream.

    Optionally takes a list of per-chunk ``asyncio.Event``s — if supplied,
    ``chat_response_stream`` awaits the i-th event before yielding the i-th
    chunk. This lets tests drive race conditions deterministically.
    """

    def __init__(
        self,
        chunks: Iterable[str],
        delay_per_chunk: float = 0.0,
        chunk_gates: list[asyncio.Event] | None = None,
    ) -> None:
        self._chunks = list(chunks)
        self._delay = delay_per_chunk
        self._chunk_gates = chunk_gates
        self.chat_response_calls = 0
        self.chat_response_stream_calls = 0

    async def chat_response(self, **kwargs) -> _FakeBridgeResponse:
        self.chat_response_calls += 1
        await asyncio.sleep(self._delay)
        return _FakeBridgeResponse(content="".join(self._chunks), metadata={})

    async def chat_response_stream(self, **kwargs) -> AsyncIterator[LLMStreamEvent]:
        self.chat_response_stream_calls += 1
        for i, chunk in enumerate(self._chunks):
            if self._chunk_gates is not None and i < len(self._chunk_gates):
                await self._chunk_gates[i].wait()
            else:
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
    gates = [asyncio.Event() for _ in range(3)]
    bridge = _FakeBridge(chunks=["a", "b", "c"], chunk_gates=gates)
    cancel = EventCancelToken()
    control = null_run_control()
    control.cancel_token = cancel
    client = CancellableLLMClient(bridge=bridge)

    # Let the first chunk emit, then cancel, then unblock the second chunk
    # to give the client a chance to observe the signal at the loop top.
    gates[0].set()
    collected: list[str] = []
    with pytest.raises(CancellationRaised):
        async for event in client.stream(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            control=control,
        ):
            if event.kind == "text_delta":
                collected.append(event.text or "")
            if len(collected) == 1:
                cancel.cancel(reason="user_request")
                gates[1].set()

    assert collected == ["a"]


@pytest.mark.asyncio
async def test_stream_raises_retract_when_retract_signal_fires_mid_stream() -> None:
    gates = [asyncio.Event() for _ in range(3)]
    bridge = _FakeBridge(chunks=["a", "b", "c"], chunk_gates=gates)
    retract = RetractSignal()
    control = null_run_control()
    control.retract_signal = retract
    client = CancellableLLMClient(bridge=bridge)

    gates[0].set()
    collected: list[str] = []
    with pytest.raises(RetractRaised) as excinfo:
        async for event in client.stream(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            control=control,
        ):
            if event.kind == "text_delta":
                collected.append(event.text or "")
            if len(collected) == 1:
                retract.request(RetractRequested(reason="user_retract"))
                gates[1].set()

    assert collected == ["a"]
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
    assert "(no reason)" in str(exc)
    assert exc.reason is None


@pytest.mark.asyncio
async def test_simultaneous_retract_and_cancel_raises_retract() -> None:
    """When both retract and cancel are set, retract takes priority
    (it's the stronger signal — cancel keeps partial output, retract
    rolls it back). Pin this invariant against future refactors of
    _raise_if_signaled."""
    bridge = _FakeBridge(chunks=["x"])
    cancel = EventCancelToken()
    retract = RetractSignal()
    cancel.cancel(reason="user_request")
    retract.request(RetractRequested(reason="user_retract"))

    control = null_run_control()
    control.cancel_token = cancel
    control.retract_signal = retract
    client = CancellableLLMClient(bridge=bridge)

    with pytest.raises(RetractRaised) as excinfo:
        await client.call(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            control=control,
        )
    assert excinfo.value.payload.reason == "user_retract"


def test_retract_raised_with_none_payload_constructs_cleanly() -> None:
    exc = RetractRaised(payload=None)
    assert "retracted" in str(exc).lower()
    assert exc.payload is None
