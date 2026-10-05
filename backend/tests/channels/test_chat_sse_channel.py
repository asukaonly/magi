"""ChatSseChannel wrapper tests — making the existing SSE stream a
first-class DeliveryRouter target."""
from __future__ import annotations

import json

import pytest

from magi.channels import chat_sse_channel as chat_sse_module
from magi.channels.chat_sse_channel import ChatSseChannel
from magi.runtime_trace import RuntimeNotificationRecord
from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt


class _StubTraceStore:
    """Minimal RuntimeTraceStore-shaped stub that captures append_notification calls."""

    def __init__(self) -> None:
        self.records: list[RuntimeNotificationRecord] = []

    async def append_notification(self, record: RuntimeNotificationRecord) -> int:
        self.records.append(record)
        return len(self.records)


@pytest.fixture
def stub_trace_store() -> _StubTraceStore:
    return _StubTraceStore()


@pytest.mark.asyncio
async def test_chat_sse_channel_deliver_writes_to_emitter_and_returns_receipt() -> None:
    """deliver() pushes the content to the chat event emitter and
    returns a receipt with the chat session/turn ID as external_message_id."""
    emitted: list = []

    async def _emit(session_id: str, payload: dict) -> str:
        """Stub emitter that captures and returns a fake message_id."""
        emitted.append((session_id, payload))
        return f"chat_msg_{len(emitted)}"

    ch = ChatSseChannel(emit_to_chat=_emit)
    # channel_type is now just the scheme; session_id comes from magi_session_id
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    content = DeliveryContent(text="hi from agent")

    receipt = await ch.deliver(target, content)

    assert len(emitted) == 1
    assert emitted[0][0] == "s1"  # session_id from magi_session_id
    assert "hi from agent" in str(emitted[0][1])
    assert receipt.channel_id == "chat_sse"
    assert receipt.magi_session_id == "s1"
    assert receipt.external_message_id == "chat_msg_1"


@pytest.mark.asyncio
async def test_chat_sse_channel_send_message_legacy_path_still_works() -> None:
    """Legacy send_message (without DeliveryReceipt return) still works."""
    emitted = []

    async def _emit(session_id, payload):
        emitted.append((session_id, payload))
        return "x"

    ch = ChatSseChannel(emit_to_chat=_emit)
    from magi_plugin_sdk.channels import OutboundContent
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s2",
        magi_user_id="u2",
    )
    result = await ch.send_message(target, OutboundContent(text="legacy text"))
    assert result is None
    assert len(emitted) == 1


# ---------------------------------------------------------------------------
# Phase G+1: trace_store-backed delivery — chat UI consumes via runtime_trace
# notifications (agent_response / agent_response_chunk channels).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("text,is_final,seq", [("hello", False, 0), ("", True, 5)])
async def test_sse_streaming_delivery_reaches_trace_store_through_router(
    stub_trace_store, monkeypatch, text, is_final, seq
):
    from types import SimpleNamespace
    from magi.channels.delivery_router import DeliveryRouter

    monkeypatch.setattr(
        "magi.runtime_trace.notification_payloads.time", SimpleNamespace(time=lambda: 123.456)
    )
    monkeypatch.setattr(chat_sse_module, "time", SimpleNamespace(time=lambda: 123.456))
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse", external_chat_id="", magi_session_id="s1", magi_user_id="u1"
    )
    router = DeliveryRouter(
        channel_registry=SimpleNamespace(get=lambda key: ch if key == "chat_sse" else None)
    )
    await router.fanout_chunk(
        targets=[target], chunk=DeliveryChunk(text=text, is_final=is_final, seq=seq)
    )
    assert len(stub_trace_store.records) == 1
    rec = stub_trace_store.records[0]
    assert (rec.channel, rec.session_id, rec.user_id, rec.created_at_ms) == (
        "agent_response_chunk",
        "s1",
        "u1",
        123456,
    )
    assert json.loads(rec.payload_json) == {
        "user_id": "u1",
        "session_id": "s1",
        "turn_id": "",
        "event": {"kind": "text_delta", "text": text},
        "is_final": is_final,
        "seq": seq,
        "timestamp": 123.456,
    }


@pytest.mark.asyncio
async def test_deliver_chunk_falls_back_to_emit_when_no_trace_store() -> None:
    """When no trace_store is wired but an emit_to_chat is, deliver_chunk
    synthesizes a chunk-shaped payload through the legacy emit path."""
    captured: list = []

    async def emit(session_id: str, payload: dict) -> str:
        captured.append((session_id, payload))
        return "synthetic_id"

    ch = ChatSseChannel(emit_to_chat=emit)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    await ch.deliver_chunk(target, DeliveryChunk(text="hi", is_final=False, seq=0))

    assert len(captured) == 1
    assert captured[0][0] == "s1"
    assert captured[0][1]["text"] == "hi"
    assert captured[0][1]["is_final"] is False


@pytest.mark.asyncio
async def test_default_emit_omits_payload_when_full_content_logging_is_disabled(
    monkeypatch,
) -> None:
    logged: list[tuple[object, ...]] = []

    class _Logger:
        def info(self, *args: object) -> None:
            logged.append(args)

    monkeypatch.setattr("magi.core.logger.get_logger", lambda _name: _Logger())
    monkeypatch.setattr(
        "magi.utils.diagnostic_logging.full_content_logging_enabled",
        lambda: False,
    )

    await chat_sse_module._default_emit(
        "session-1",
        {"text": "SSE-CONTENT-CANARY", "is_final": False},
    )

    assert "SSE-CONTENT-CANARY" not in str(logged)
    assert "payload_fields" in str(logged)
    assert "is_final" in str(logged)
    assert "text" in str(logged)


# ---------------------------------------------------------------------------
# Phase G+1 Step 1: DeliveryContent/DeliveryChunk carry the richer
# agent_response fields so ChatSseChannel can become the single canonical
# writer (replacing ChatRuntimeNotifier). Fields default to None → omitted,
# so existing callers see zero behavior change.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("rich", [False, True])
async def test_sse_delivery_preserves_complete_wire_payload_and_scoped_receipt(
    stub_trace_store, monkeypatch, rich
):
    from types import SimpleNamespace
    from magi.channels.delivery_router import DeliveryRouter

    monkeypatch.setattr(
        "magi.runtime_trace.notification_payloads.time", SimpleNamespace(time=lambda: 123.456)
    )
    monkeypatch.setattr(chat_sse_module, "time", SimpleNamespace(time=lambda: 123.456))
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse", external_chat_id="", magi_session_id="s1", magi_user_id="u1"
    )
    extras = (
        {
            "turn_id": "t1",
            "message_id": "m1",
            "message_kind": "assistant",
            "persona_id": "p1",
            "trace_summary": {"nodes": 3},
            "trace_available": True,
            "ux_plan": {"shape": "reply"},
            "message_payload": {"text": "full reply"},
        }
        if rich
        else {}
    )
    attachments = ({"kind": "image", "uri": "image.png"},) if rich else ()
    content = DeliveryContent(text="full reply", attachments=attachments, **extras)
    router = DeliveryRouter(
        channel_registry=SimpleNamespace(get=lambda key: ch if key == "chat_sse" else None)
    )
    result = await router.fanout_deliver(targets=[target], content=content)
    assert result.failures == ()
    assert result.receipts == (
        DeliveryReceipt(
            channel_id="chat_sse",
            external_message_id=None,
            delivered_at_ms=123456,
            magi_session_id="s1",
        ),
    )
    assert len(stub_trace_store.records) == 1
    rec = stub_trace_store.records[0]
    assert (rec.channel, rec.session_id, rec.user_id, rec.created_at_ms) == (
        "agent_response",
        "s1",
        "u1",
        123456,
    )
    expected = {
        "user_id": "u1",
        "session_id": "s1",
        "content": "full reply",
        "is_final": True,
        "timestamp": 123.456,
    }
    if rich:
        expected.update(extras, attachments=[{"kind": "image", "uri": "image.png"}])
    assert json.loads(rec.payload_json) == expected


@pytest.mark.asyncio
async def test_deliver_chunk_carries_full_event_when_supplied(
    stub_trace_store: _StubTraceStore,
) -> None:
    """When DeliveryChunk supplies a full event dict (e.g. a tool_call event),
    deliver_chunk forwards it verbatim instead of forcing the hardcoded
    text_delta shape."""
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    chunk = DeliveryChunk(
        text="",
        is_final=False,
        seq=2,
        turn_id="t1",
        event={"kind": "tool_call_start", "tool_name": "search"},
        persona_id="p1",
    )

    await ch.deliver_chunk(target, chunk)

    payload = json.loads(stub_trace_store.records[0].payload_json)
    assert payload["event"]["kind"] == "tool_call_start"
    assert payload["event"]["tool_name"] == "search"
    assert payload["turn_id"] == "t1"
    assert payload["persona_id"] == "p1"


def test_delivery_content_round_trips_convergence_fields() -> None:
    """DeliveryContent.to_dict/from_dict preserves the new convergence fields."""
    content = DeliveryContent(
        text="x",
        turn_id="t1",
        message_id="m1",
        trace_available=True,
        ux_plan={"a": 1},
    )
    restored = DeliveryContent.from_dict(content.to_dict())
    assert restored.turn_id == "t1"
    assert restored.message_id == "m1"
    assert restored.trace_available is True
    assert restored.ux_plan == {"a": 1}
