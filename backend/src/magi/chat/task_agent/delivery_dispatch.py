"""Delivery dispatch port consumed by the chat task-agent layer."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from magi.delivery.contracts import DeliveryFanoutResult
from magi.llm.streaming_events import LLMStreamEvent
from magi_plugin_sdk.delivery import DeliveryContent


class ChatDeliveryDispatchPort(Protocol):
    """Narrow delivery surface injected into chat coordination."""

    async def deliver_final_response(
        self,
        request: Any,
        *,
        response_text: str,
        attachments: Any = (),
        content: DeliveryContent | None = None,
        exclude_chat_sse: bool = False,
        chat_sse_only: bool = False,
        exclude_channel_types: Iterable[str] = (),
    ) -> DeliveryFanoutResult:
        """Deliver a final assistant response to configured channel targets."""

    async def dispatch_stream_chunk(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        is_final: bool,
        seq: int,
        turn_id: str | None = None,
        event: LLMStreamEvent | None = None,
        persona_id: str | None = None,
    ) -> None:
        """Dispatch one streaming response chunk to configured channel targets."""

    async def retract_run_deliveries(
        self,
        *,
        session_id: str,
        run_id: str,
    ) -> None:
        """Retract messages delivered for one chat run."""


__all__ = ["ChatDeliveryDispatchPort"]
