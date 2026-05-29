"""End-to-end Phase G+1 wireup tests.

Exercises the new delivery wire-up at the coordinator level — that is,
streamed text deltas dispatched via ``ChatExecutionCoordinator.dispatch_stream_chunk``
fan out to every configured channel (chat_sse + telegram-like), and the
final assembled response delivered via ``coordinator.execute()`` reaches
all of those channels as well.

These tests use real ``Channel`` subclasses (no Mocks) — they record
``deliver_chunk`` / ``deliver`` calls so we can assert the exact wire
contract:

  - chat_sse channel: gets N ``deliver_chunk`` calls (one per text_delta
    + one final boundary) AND a final ``deliver`` call with the
    assembled text.
  - telegram-like channel: gets the same N ``deliver_chunk`` calls,
    buffers them internally, and on ``is_final=True`` either flushes
    the assembled text (chunk path) and/or receives ``deliver`` (fanout
    path).

Why these matter: Task 7 wired ``dispatch_stream_chunk`` on the
coordinator, Task 8 wired the DirectLLMHandler to call it for each
text_delta, and Task 9 wired the user_prefs_provider that controls
which channels get the final fanout. This file is the integration
proof that those three pieces compose end-to-end without surprises.
"""

from __future__ import annotations

import pytest

from magi.agent.task_agents.chat import (
    ChatRuntimeContext,
    ExecutionMode,
    UserMessagePayload,
)
from magi.agent.task_agents.chat import ExecutionHandlerRegistry
from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.chat.contracts import IntentDecision
from magi.agent.task_agents.chat.fact_classifier import (
    ChatFactClassifier,
    IncomingFactKind,
)
from magi.agent.runtime.contracts import FactRecord
from magi.agent.run.snapshot import RunSnapshot
from magi.agent.task_agents.common.contracts import (
    ExecutionRequest,
    ExecutionResult,
    ToolSelection,
)
from magi.events.events import EventTypes
from magi.tools.context_routing import RouteDecision

from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt


# ---------------------------------------------------------------------------
# Test fixtures: real Channel subclasses that record their calls.
# ---------------------------------------------------------------------------


class _RecordingSseChannel(Channel):
    """Real Channel subclass that records both deliver_chunk and deliver.

    Mirrors the shape of the production ``ChatSseChannel`` (one record per
    deliver_chunk call, deliver returns a DeliveryReceipt). We also keep a
    minimal in-memory ``trace_records`` list so the test can assert that
    chunks would have been observable by a polling chat-UI consumer.
    """

    supports_streaming = True

    def __init__(self, channel_type: str = "chat_sse") -> None:
        self._t = channel_type
        self.chunks: list[tuple[ChannelTarget, DeliveryChunk]] = []
        self.delivers: list[tuple[ChannelTarget, DeliveryContent]] = []
        # Stub "trace store" — what a chat UI would poll.
        self.trace_records: list[dict] = []

    @property
    def channel_type(self) -> str:
        return self._t

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_message(
        self, target: ChannelTarget, content: OutboundContent
    ) -> None:
        return None

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        return None

    async def deliver_chunk(
        self, target: ChannelTarget, chunk: DeliveryChunk
    ) -> None:
        self.chunks.append((target, chunk))
        # Mirror ChatSseChannel: one trace record per chunk.
        self.trace_records.append(
            {
                "kind": "agent_response_chunk",
                "text": chunk.text,
                "is_final": chunk.is_final,
                "seq": chunk.seq,
                "session_id": target.channel_type,
            }
        )

    async def deliver(
        self, target: ChannelTarget, content: DeliveryContent
    ) -> DeliveryReceipt:
        self.delivers.append((target, content))
        # Mirror ChatSseChannel: one trace record for the assembled final.
        self.trace_records.append(
            {
                "kind": "agent_response",
                "text": content.text,
                "session_id": target.channel_type,
            }
        )
        return DeliveryReceipt(
            channel_id=target.channel_type,
            external_message_id=None,
            delivered_at_ms=0,
        )


class _RecordingTelegramChannel(Channel):
    """Telegram-like channel that buffers chunks per (channel, chat) and
    assembles the full text on the final boundary.

    Mirrors Task 10's behavior so this test doesn't depend on the
    plugin repo. It supports both the chunk path (assembles on its own)
    and the deliver() path (records the assembled content the host sends).
    """

    supports_streaming = True

    def __init__(self) -> None:
        self._buffers: dict[tuple[str, str], list[str]] = {}
        # Assembled text from buffered chunks, captured at is_final=True.
        self.assembled_sends: list[tuple[ChannelTarget, str]] = []
        # Final deliver() calls from the coordinator's fanout path.
        self.delivers: list[tuple[ChannelTarget, DeliveryContent]] = []

    @property
    def channel_type(self) -> str:
        return "telegram"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_message(
        self, target: ChannelTarget, content: OutboundContent
    ) -> None:
        return None

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        return None

    async def deliver_chunk(
        self, target: ChannelTarget, chunk: DeliveryChunk
    ) -> None:
        key = (target.channel_type, target.external_chat_id)
        if chunk.text:
            self._buffers.setdefault(key, []).append(chunk.text)
        if chunk.is_final:
            parts = self._buffers.pop(key, [])
            if parts:
                self.assembled_sends.append((target, "".join(parts)))

    async def deliver(
        self, target: ChannelTarget, content: DeliveryContent
    ) -> DeliveryReceipt:
        self.delivers.append((target, content))
        return DeliveryReceipt(
            channel_id="telegram",
            external_message_id="tg:1",
            delivered_at_ms=0,
        )


class _StubRegistry:
    """Minimal ChannelRegistry that DeliveryRouter can ``get(key)`` on."""

    def __init__(self, channels: dict[str, Channel]) -> None:
        self._channels = channels

    def get(self, key: str) -> Channel | None:
        return self._channels.get(key)


class _FakeToolRegistry:
    def list_tools(self) -> list[str]:
        return []


class _FakeContextDecider:
    """Minimal ContextDecider that returns a fixed RouteDecision."""

    def __init__(self, decision: RouteDecision) -> None:
        self._decision = decision
        self.tool_registry = _FakeToolRegistry()
        self.last_decision_context: object | None = None

    async def decide(self, user_message: str, decision_context: object):
        self.last_decision_context = decision_context
        return self._decision


def _two_channel_prefs_provider():
    """User has explicitly opted into chat_sse + telegram."""

    async def provider(user_id: str) -> dict:
        return {"delivery_channels": ["chat_sse", "telegram"]}

    return provider


def _build_coordinator(
    *,
    channels: dict[str, Channel],
    prefs_provider,
) -> ChatExecutionCoordinator:
    """Construct a coordinator wired with the channel registry + prefs provider."""

    decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=[],
            reasoning="",
        )
    )
    return ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        channel_registry=_StubRegistry(channels),
        user_prefs_provider=prefs_provider,
    )


# ---------------------------------------------------------------------------
# Test A: streaming path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_stream_chunk_reaches_both_channels() -> None:
    """3 text deltas + 1 final boundary chunk must reach BOTH
    chat_sse and telegram channels.

    Asserts the wire contract:
      - chat_sse gets exactly 4 deliver_chunk calls in order
        (one per delta + one for the final boundary).
      - telegram gets the same 4 calls, buffers them internally, and on
        is_final=True flushes "hello world".
      - The trace_store stub on the SSE channel has 4 records — what a
        chat UI consumer would observe.
    """
    sse = _RecordingSseChannel()
    tg = _RecordingTelegramChannel()
    coordinator = _build_coordinator(
        channels={"chat_sse": sse, "telegram": tg},
        prefs_provider=_two_channel_prefs_provider(),
    )

    # Stream 3 text deltas
    for i, text in enumerate(["he", "llo", " world"]):
        await coordinator.dispatch_stream_chunk(
            session_id="s1",
            user_id="u1",
            text=text,
            is_final=False,
            seq=i,
        )
    # + 1 final boundary chunk
    await coordinator.dispatch_stream_chunk(
        session_id="s1",
        user_id="u1",
        text="",
        is_final=True,
        seq=3,
    )

    # --- chat_sse assertions ---
    assert len(sse.chunks) == 4, sse.chunks
    assert [c.text for _, c in sse.chunks] == ["he", "llo", " world", ""]
    assert [c.seq for _, c in sse.chunks] == [0, 1, 2, 3]
    assert [c.is_final for _, c in sse.chunks] == [False, False, False, True]
    # All targets reached the SSE channel under the composite key.
    assert all(t.channel_type == "chat_sse:s1" for t, _ in sse.chunks)
    # The trace-store stub (what the chat UI polls) saw all 4.
    assert len(sse.trace_records) == 4
    assert sse.trace_records[-1]["is_final"] is True

    # --- telegram assertions ---
    # Telegram doesn't expose its raw chunk list, but its assembler does:
    assert len(tg.assembled_sends) == 1
    target, assembled = tg.assembled_sends[0]
    assert assembled == "hello world"
    assert target.channel_type == "telegram"
    assert target.external_chat_id == "u1"


@pytest.mark.asyncio
async def test_dispatch_stream_chunk_uses_default_when_no_prefs() -> None:
    """When the prefs provider returns empty, only chat_sse should be hit
    (telegram is not in the default fallback target list).

    This guards against accidentally fanning out to ALL registered
    channels when the user has no explicit preference.
    """
    sse = _RecordingSseChannel()
    tg = _RecordingTelegramChannel()

    async def empty_prefs(user_id: str) -> dict:
        return {}

    coordinator = _build_coordinator(
        channels={"chat_sse": sse, "telegram": tg},
        prefs_provider=empty_prefs,
    )

    await coordinator.dispatch_stream_chunk(
        session_id="s1", user_id="u1", text="hi", is_final=False, seq=0,
    )
    await coordinator.dispatch_stream_chunk(
        session_id="s1", user_id="u1", text="", is_final=True, seq=1,
    )

    # Default = chat_sse only.
    assert len(sse.chunks) == 2
    # Telegram untouched.
    assert tg.assembled_sends == []


# ---------------------------------------------------------------------------
# Test B: final-fanout path via execute()
# ---------------------------------------------------------------------------


def _build_context_with_run_id(*, user_id: str, session_id: str, run_id: str) -> ChatRuntimeContext:
    fact = FactRecord(
        agent_id=f"chat:{user_id}",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": user_id, "session_id": session_id, "content": "hi"},
    )
    return ChatRuntimeContext(
        latest_fact=fact,
        recent_facts=[fact],
        batch_facts=[fact],
        agent_id=user_id,
        agent_type="chat",
        runtime_key=f"chat:{user_id}",
        user_id=user_id,
        session_id=session_id,
        history_key=f"{user_id}::{session_id}",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(
            dict(fact.payload), fallback_user_id=user_id,
        ),
        session_run_id=run_id,
    )


@pytest.mark.asyncio
async def test_execute_fanout_calls_deliver_on_both_channels() -> None:
    """After the node-sequence runner returns its assembled result,
    coordinator.execute() must call ``deliver()`` on BOTH channels the
    user opted into.

    Pairs with Test A: A covers the streaming chunk path; this covers
    the final-assembled deliver path. Together they prove the Phase G+1
    wire-up reaches all configured channels through both seams.
    """
    sse = _RecordingSseChannel()
    tg = _RecordingTelegramChannel()
    coordinator = _build_coordinator(
        channels={"chat_sse": sse, "telegram": tg},
        prefs_provider=_two_channel_prefs_provider(),
    )

    # Stub the node-sequence runner so execute() short-circuits with a
    # canned ExecutionResult — same pattern as Task 9's integration tests.
    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="hello world",
    )

    class _FakeRunner:
        async def run_with_snapshot(
            self, *, run_id, node_specs, request, resume_from,
        ):
            return canned_result, RunSnapshot(
                run_id=run_id,
                graph=tuple(spec.node_type for spec in node_specs),
                cursor=len(node_specs),
                node_states={},
            )

    coordinator._node_sequence_runner = _FakeRunner()

    route = RouteDecision(
        profile="chat",
        graph_shape="reply",
        complexity="simple",
        tools=[],
        reasoning="",
    )
    context = _build_context_with_run_id(
        user_id="u1", session_id="s1", run_id="run-1",
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=route,
        reasoning="",
    )
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )

    result = await coordinator.execute(request)
    assert result is canned_result

    # --- chat_sse: one deliver call with the assembled text ---
    assert len(sse.delivers) == 1
    sse_target, sse_content = sse.delivers[0]
    assert sse_content.text == "hello world"
    # Composite key — same one resolve_delivery_targets constructs.
    assert sse_target.channel_type == "chat_sse:s1"
    assert sse_target.external_chat_id == "u1"

    # --- telegram: one deliver call with the assembled text ---
    assert len(tg.delivers) == 1
    tg_target, tg_content = tg.delivers[0]
    assert tg_content.text == "hello world"
    assert tg_target.channel_type == "telegram"
    assert tg_target.external_chat_id == "u1"


# ---------------------------------------------------------------------------
# Test C: streaming + final fanout composed together (full e2e)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_chunks_then_final_fanout_reaches_both_channels() -> None:
    """Full lifecycle: the coordinator dispatches streaming chunks AND
    fans out the final assembled response. Both channels must see both.

    This is the most realistic "what a streaming chat turn looks like
    end-to-end at the coordinator level" test.
    """
    sse = _RecordingSseChannel()
    tg = _RecordingTelegramChannel()
    coordinator = _build_coordinator(
        channels={"chat_sse": sse, "telegram": tg},
        prefs_provider=_two_channel_prefs_provider(),
    )

    # --- streaming phase ---
    for i, text in enumerate(["he", "llo", " world"]):
        await coordinator.dispatch_stream_chunk(
            session_id="s1", user_id="u1", text=text, is_final=False, seq=i,
        )
    await coordinator.dispatch_stream_chunk(
        session_id="s1", user_id="u1", text="", is_final=True, seq=3,
    )

    # --- final fanout phase ---
    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM, response_text="hello world",
    )

    class _FakeRunner:
        async def run_with_snapshot(
            self, *, run_id, node_specs, request, resume_from,
        ):
            return canned_result, RunSnapshot(
                run_id=run_id,
                graph=tuple(spec.node_type for spec in node_specs),
                cursor=len(node_specs),
                node_states={},
            )

    coordinator._node_sequence_runner = _FakeRunner()
    route = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    )
    context = _build_context_with_run_id(
        user_id="u1", session_id="s1", run_id="run-1",
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=route,
        reasoning="",
    )
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )
    await coordinator.execute(request)

    # --- assertions: both channels saw streaming AND deliver ---
    # chat_sse: 4 chunks + 1 deliver
    assert len(sse.chunks) == 4
    assert len(sse.delivers) == 1
    assert sse.delivers[0][1].text == "hello world"

    # telegram: 1 assembled (from chunks) + 1 deliver
    assert len(tg.assembled_sends) == 1
    assert tg.assembled_sends[0][1] == "hello world"
    assert len(tg.delivers) == 1
    assert tg.delivers[0][1].text == "hello world"
