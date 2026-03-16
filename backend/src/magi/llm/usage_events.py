"""LLM usage event publication helpers."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..events.backend import MessageBusBackend
from ..events.events import Event, EventLevel, EventTypes

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LLMCallEventPayload:
    """Normalized payload for a completed LLM call."""

    provider: str
    model: str
    request_kind: str
    success: bool
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    usage_available: bool = False
    latency_ms: int = 0
    error: str | None = None
    correlation_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    agent_id: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_event_data(self) -> dict[str, Any]:
        """Convert payload to a message-bus-safe dictionary."""
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "request_kind": self.request_kind,
            "prompt_tokens": int(self.prompt_tokens or 0),
            "completion_tokens": int(self.completion_tokens or 0),
            "total_tokens": int(self.total_tokens or 0),
            "usage_available": bool(self.usage_available),
            "latency_ms": int(self.latency_ms or 0),
            "success": bool(self.success),
            "error": self.error,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "agent_id": self.agent_id,
            "created_at": float(self.created_at),
        }


class LLMUsageEventPublisher:
    """Runtime-scoped publisher for LLM usage events."""

    def __init__(self, message_bus: MessageBusBackend | None = None) -> None:
        self._message_bus = message_bus

    def configure(self, message_bus: MessageBusBackend | None) -> None:
        self._message_bus = message_bus

    async def publish(self, payload: LLMCallEventPayload) -> None:
        if self._message_bus is None:
            return

        try:
            await self._message_bus.publish(
                Event(
                    type=EventTypes.LLM_CALL_COMPLETED,
                    data=payload.to_event_data(),
                    source="llm_provider_bridge",
                    level=EventLevel.INFO if payload.success else EventLevel.ERROR,
                    correlation_id=payload.correlation_id,
                )
            )
        except Exception as exc:
            logger.warning("Failed to publish LLM usage event: %s", exc)


async def publish_llm_call_event(
    payload: LLMCallEventPayload,
    publisher: LLMUsageEventPublisher | None = None,
) -> None:
    """Publish an LLM usage event without surfacing recorder failures upstream."""
    if publisher is None:
        return
    await publisher.publish(payload)
