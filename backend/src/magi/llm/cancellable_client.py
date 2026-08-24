"""Cancellable LLM client wrapping LLMProviderBridge with RunControl polling.

This is the cancellable LLM entry point used by the unified agent loop and
domain orchestration planners. It wraps
:class:`~magi.llm.provider_bridge.LLMProviderBridge` and polls the
caller-supplied :class:`~magi.control.run_control.RunControl` between
stream chunks, raising :class:`CancellationRaised` or
:class:`RetractRaised` so the caller can project the corresponding run state.

Design notes
------------
* Suspend and detach are *not* raised here — those are graceful
  boundaries observed by the calling node, not transport aborts.
* Run inputs are not drained here either — they are consumed at
  agent-step boundaries, not mid-LLM-call.
* Non-streaming :meth:`call` cannot poll mid-flight, so it only checks
  cancel/retract once before dispatch. Streaming :meth:`stream` checks
  before every yielded chunk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from ..control.run_control import (
    RetractRequested,
    RunControl,
)
from .provider_bridge import LLMProviderBridge, _coerce_thinking_depth
from .streaming_events import LLMStreamEvent


__all__ = [
    "CancellableLLMClient",
    "CancellationRaised",
    "RetractRaised",
    "LLMCallResult",
]


@dataclass(slots=True, frozen=True)
class LLMCallResult:
    """Result of a non-streaming LLM call via CancellableLLMClient."""

    content: str
    metadata: dict[str, Any]


class CancellationRaised(Exception):
    """Raised when ``CancelToken.is_cancelled()`` returns True during a
    cancellable LLM call."""

    def __init__(self, reason: str | None) -> None:
        super().__init__(f"LLM call cancelled: {reason or '(no reason)'}")
        self.reason = reason


class RetractRaised(Exception):
    """Raised when ``RetractSignal.is_requested()`` is true during a
    cancellable LLM call."""

    def __init__(self, payload: RetractRequested | None) -> None:
        super().__init__(f"LLM call retracted: {payload.reason if payload else 'unknown'}")
        self.payload = payload


class CancellableLLMClient:
    """Thin wrapper over LLMProviderBridge that respects RunControl.

    Construct one per provider bridge; the bundle is supplied per call.
    """

    __slots__ = ("_bridge",)

    def __init__(self, bridge: LLMProviderBridge) -> None:
        self._bridge = bridge

    async def call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        control: RunControl,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        disable_thinking: bool = True,
        thinking_depth: Any | None = None,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        event_context: dict[str, Any] | None = None,
        **extra: Any,
    ) -> LLMCallResult:
        """Non-streaming call. Polls cancel/retract once before dispatch."""
        await self._raise_if_signaled(control)

        kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "temperature": temperature,
            "disable_thinking": disable_thinking,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if thinking_depth is not None:
            kwargs["thinking_depth"] = thinking_depth
        if json_mode:
            kwargs["json_mode"] = json_mode
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        if event_context is not None:
            kwargs["event_context"] = event_context
        kwargs.update(extra)

        provider_response = await self._bridge.chat_response(**kwargs)
        return LLMCallResult(
            content=getattr(provider_response, "content", "") or "",
            metadata=dict(getattr(provider_response, "metadata", {}) or {}),
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        control: RunControl,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        disable_thinking: bool = True,
        thinking_depth: Any | None = None,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        event_context: dict[str, Any] | None = None,
        **extra: Any,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming call. Polls cancel/retract before every yielded chunk.

        Raises :class:`CancellationRaised` or :class:`RetractRaised` on
        signal. Detach/suspend are *not* raised — those are observed by
        the calling node at iteration boundaries.
        """
        await self._raise_if_signaled(control)

        # chat_response_stream does NOT accept disable_thinking; resolve to
        # thinking_depth here so we never forward an unknown kwarg.
        resolved_thinking = _coerce_thinking_depth(thinking_depth, disable_thinking)

        kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "temperature": temperature,
            "thinking_depth": resolved_thinking,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["json_mode"] = json_mode
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        if event_context is not None:
            kwargs["event_context"] = event_context
        kwargs.update(extra)

        async for event in self._bridge.chat_response_stream(**kwargs):
            await self._raise_if_signaled(control)
            yield event

    async def _raise_if_signaled(self, control: RunControl) -> None:
        """Check RunControl signals and raise if either retract or cancel is set.

        Retract is checked before cancel because it is the stronger signal —
        cancel preserves partial output while retract rolls it back. Suspend
        and detach are not raised here; those are graceful boundaries observed
        at node iteration boundaries by the calling orchestrator loop.
        """
        # Instance method (not @staticmethod) so subclasses can override
        # to add tracing/telemetry around the signal checks without
        # changing the call sites in call()/stream().
        if control.retract_signal.is_requested():
            raise RetractRaised(control.retract_signal.payload)
        if await control.cancel_token.is_cancelled():
            raise CancellationRaised(control.cancel_token.reason)
