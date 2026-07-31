"""ChatSseChannel wrapper tests — making the existing SSE stream a
first-class DeliveryRouter target."""
from __future__ import annotations

import json

import pytest

from magi.channels import chat_sse_channel as chat_sse_module
from magi.channels.chat_sse_channel import ChatSseChannel
from magi.runtime_trace import RuntimeNotificationRecord
from magi_plugin_sdk.channels import Channel, ChannelTarget
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


def test_chat_sse_channel_is_a_channel() -> None:
    ch = ChatSseChannel()
    assert isinstance(ch, Channel)


def test_chat_sse_channel_capability_flags() -> None:
    """chat SSE supports streaming + attachments, NOT revision (the
    frontend renders SSE chunks as immutable cards; edits would require
    a separate update event which Phase G doesn't model yet)."""
    ch = ChatSseChannel()
    assert ch.supports_streaming is True
    assert ch.supports_attachments is True
    assert ch.supports_revision is False


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
async def test_deliver_chunk_appends_agent_response_chunk_record(
    stub_trace_store: _StubTraceStore,
) -> None:
    """deliver_chunk writes an agent_response_chunk RuntimeNotificationRecord
    carrying the stream event in ``payload.event`` (channel is the sole writer)."""
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    chunk = DeliveryChunk(text="hello", is_final=False, seq=0)

    await ch.deliver_chunk(target, chunk)

    assert len(stub_trace_store.records) == 1
    rec = stub_trace_store.records[0]
    assert rec.channel == "agent_response_chunk"
    assert rec.session_id == "s1"
    assert rec.user_id == "u1"
    payload = json.loads(rec.payload_json)
    assert payload["event"]["kind"] == "text_delta"
    assert payload["event"]["text"] == "hello"
    assert payload["session_id"] == "s1"
    assert payload["user_id"] == "u1"
    assert payload["is_final"] is False


@pytest.mark.asyncio
async def test_deliver_chunk_final_marks_payload_is_final(
    stub_trace_store: _StubTraceStore,
) -> None:
    """A final chunk emits a single record with payload.is_final=True (the
    finish boundary is conveyed via is_final, not a separate 'finish' kind)."""
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    chunk = DeliveryChunk(text="", is_final=True, seq=5)

    await ch.deliver_chunk(target, chunk)

    assert len(stub_trace_store.records) == 1
    rec = stub_trace_store.records[0]
    assert rec.channel == "agent_response_chunk"
    payload = json.loads(rec.payload_json)
    assert payload["is_final"] is True
    assert payload["event"]["kind"] == "text_delta"
    assert payload["event"]["text"] == ""


@pytest.mark.asyncio
async def test_deliver_writes_agent_response_record_and_returns_receipt(
    stub_trace_store: _StubTraceStore,
) -> None:
    """deliver() writes an agent_response RuntimeNotificationRecord with
    content/is_final, and returns a DeliveryReceipt with external_message_id=None."""
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    content = DeliveryContent(text="full reply")

    receipt = await ch.deliver(target, content)

    assert isinstance(receipt, DeliveryReceipt)
    assert receipt.channel_id == "chat_sse"
    assert receipt.magi_session_id == "s1"
    assert receipt.external_message_id is None
    assert len(stub_trace_store.records) == 1
    rec = stub_trace_store.records[0]
    assert rec.channel == "agent_response"
    assert rec.session_id == "s1"
    assert rec.user_id == "u1"
    payload = json.loads(rec.payload_json)
    assert payload["content"] == "full reply"
    assert payload["session_id"] == "s1"
    assert payload["user_id"] == "u1"
    assert payload["is_final"] is True


@pytest.mark.asyncio
async def test_deliver_falls_back_to_emit_when_no_trace_store() -> None:
    """Backward compat — legacy emit_to_chat path still works when trace_store=None."""
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
    receipt = await ch.deliver(target, DeliveryContent(text="hi"))

    assert len(captured) == 1
    assert captured[0][0] == "s1"
    assert receipt.channel_id == "chat_sse"
    assert receipt.magi_session_id == "s1"
    assert receipt.external_message_id == "synthetic_id"


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
async def test_deliver_chunk_raises_when_neither_trace_store_nor_emit() -> None:
    """When BOTH trace_store and emit_to_chat are absent (default _emit is
    still installed in this branch by current code path), we still must avoid
    silently dropping. The SDK default deliver_chunk raises NotImplementedError;
    by leaving _emit at the default, we accept the legacy synthetic path."""
    ch = ChatSseChannel()  # no trace_store, no emit_to_chat → falls back to _default_emit
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    # Should not raise; _default_emit logs and returns a synthetic id.
    await ch.deliver_chunk(target, DeliveryChunk(text="x", is_final=False, seq=0))


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


@pytest.mark.asyncio
async def test_deliver_returns_receipt_with_scheme_channel_id_and_magi_session_id():
    """Pin the new receipt shape: channel_id is the scheme only, and the
    magi_session_id field carries the session for retract-by-session lookups."""
    store = _StubTraceStore()
    ch = ChatSseChannel(trace_store=store)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s-123",
        magi_user_id="u-7",
    )
    receipt = await ch.deliver(target, DeliveryContent(text="hi"))
    assert receipt.channel_id == "chat_sse"  # scheme only
    assert receipt.magi_session_id == "s-123"  # new field carries the session
    assert receipt.external_message_id is None


# ---------------------------------------------------------------------------
# Phase G+1 Step 1: DeliveryContent/DeliveryChunk carry the richer
# agent_response fields so ChatSseChannel can become the single canonical
# writer (replacing ChatRuntimeNotifier). Fields default to None → omitted,
# so existing callers see zero behavior change.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_carries_convergence_fields_when_supplied(
    stub_trace_store: _StubTraceStore,
) -> None:
    """When DeliveryContent supplies the richer fields, deliver() writes them
    into the agent_response payload."""
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )
    content = DeliveryContent(
        text="full reply",
        turn_id="t1",
        message_id="m1",
        message_kind="assistant",
        persona_id="p1",
        trace_summary={"nodes": 3},
        trace_available=True,
        ux_plan={"shape": "reply"},
        orchestration_id="orc1",
    )

    await ch.deliver(target, content)

    payload = json.loads(stub_trace_store.records[0].payload_json)
    assert payload["turn_id"] == "t1"
    assert payload["message_id"] == "m1"
    assert payload["message_kind"] == "assistant"
    assert payload["persona_id"] == "p1"
    assert payload["trace_summary"] == {"nodes": 3}
    assert payload["trace_available"] is True
    assert payload["ux_plan"] == {"shape": "reply"}
    assert payload["orchestration_id"] == "orc1"
    # base fields unchanged
    assert payload["content"] == "full reply"
    assert payload["is_final"] is True


@pytest.mark.asyncio
async def test_deliver_omits_convergence_fields_when_not_supplied(
    stub_trace_store: _StubTraceStore,
) -> None:
    """Zero-behavior-change guard: a plain DeliveryContent (no convergence
    fields) produces exactly the legacy agent_response payload keys."""
    ch = ChatSseChannel(trace_store=stub_trace_store)
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )

    await ch.deliver(target, DeliveryContent(text="plain"))

    payload = json.loads(stub_trace_store.records[0].payload_json)
    assert set(payload.keys()) == {"user_id", "session_id", "content", "is_final", "timestamp"}


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
