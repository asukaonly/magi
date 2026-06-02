"""When DeliveryRouter is the canonical streaming path, the legacy
ChatRuntimeNotifier.emit_stream_event must not double-write.

Phase G+1 introduced ``ChatSseChannel.deliver_chunk`` which writes the
canonical ``agent_response_chunk`` row to ``runtime_trace_store`` for every
text delta. The legacy path
(``ChatStreamingMixin._build_stream_sink`` ->
``ChatRuntimeNotifier.emit_stream_event``) also writes that row, so the
session-keyed chat UI poller would render each chunk twice. This module
pins the guard: when ``set_delivery_router_active(True)`` is called on the
notifier, ``emit_stream_event`` becomes a no-op; otherwise legacy behavior
is preserved (so deployments without channels still see chunks).
"""
from __future__ import annotations

import pytest

from magi.chat.task_agent.postprocess.notifications import ChatRuntimeNotifier
from magi.llm.streaming_events import LLMStreamEvent
from magi.runtime_trace import RuntimeNotificationRecord


class _StubTraceStore:
    def __init__(self) -> None:
        self.records: list[RuntimeNotificationRecord] = []

    async def append_notification(self, rec: RuntimeNotificationRecord) -> int:
        self.records.append(rec)
        return len(self.records)


def _unused_read_service_factory() -> None:
    return None


@pytest.mark.asyncio
async def test_emit_stream_event_skipped_when_delivery_router_active() -> None:
    store = _StubTraceStore()
    notifier = ChatRuntimeNotifier(
        runtime_trace_store=store,
        chat_read_service_factory=_unused_read_service_factory,
    )
    notifier.set_delivery_router_active(True)
    await notifier.emit_stream_event(
        event=LLMStreamEvent(kind="text_delta", text="hi"),
        user_id="u",
        session_id="s",
        turn_id="t",
    )
    assert store.records == [], (
        "emit_stream_event must skip the write when the DeliveryRouter is "
        "the canonical streaming path; otherwise the chat UI's session-keyed "
        "poller would render every chunk twice."
    )


@pytest.mark.asyncio
async def test_emit_stream_event_writes_when_delivery_router_inactive() -> None:
    store = _StubTraceStore()
    notifier = ChatRuntimeNotifier(
        runtime_trace_store=store,
        chat_read_service_factory=_unused_read_service_factory,
    )
    # Default: delivery router inactive -> legacy behavior preserved so
    # deployments without channels still see streaming chunks.
    await notifier.emit_stream_event(
        event=LLMStreamEvent(kind="text_delta", text="hi"),
        user_id="u",
        session_id="s",
        turn_id="t",
    )
    assert len(store.records) == 1
    rec = store.records[0]
    assert rec.channel == "agent_response_chunk"
    assert rec.turn_id == "t"
