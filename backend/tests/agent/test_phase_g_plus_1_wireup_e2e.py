"""End-to-end Phase G+1 wireup tests.

Exercises the new delivery wire-up at the coordinator level — that is,
streamed text deltas dispatched via ``ChatExecutionCoordinator.dispatch_stream_chunk``
fan out to every configured channel (chat_sse + telegram-like), and the
final assembled response delivered through the postprocess seam reaches
all of those channels only after the local outcome is durable.

These tests use real ``Channel`` subclasses (no Mocks) — they record
``deliver_chunk`` / ``deliver`` calls so we can assert the exact wire
contract:

  - chat_sse channel: gets N ``deliver_chunk`` calls during streaming and
    receives a final ``deliver`` only for non-streamed turns.
  - telegram-like channel: skips chunks and receives the assembled final
    response from postprocess after persistence.

Why these matter: Task 7 wired ``dispatch_stream_chunk`` on the
coordinator, Task 8 wired the DirectLLMHandler to call it for each
text_delta, and Task 9 wired the user_prefs_provider that controls
which channels get the final fanout. This file is the integration
proof that those three pieces compose end-to-end without surprises.
"""

from __future__ import annotations

import pytest

from magi.agent.task_agents.handlers import (
    ChatRuntimeContext,
    ExecutionMode,
    UserMessagePayload,
)
from magi.agent.task_agents.handlers import ExecutionHandlerRegistry
from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.handlers.contracts import IntentDecision
from magi.chat.task_agent.fact_classifier import (
    ChatFactClassifier,
    IncomingFactKind,
)
from magi.agent.runtime.contracts import FactRecord
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
        # Mirror ChatSseChannel: one trace record per chunk. Phase G+2 reads
        # the session id from the dedicated magi_session_id field.
        self.trace_records.append(
            {
                "kind": "agent_response_chunk",
                "text": chunk.text,
                "is_final": chunk.is_final,
                "seq": chunk.seq,
                "session_id": target.magi_session_id,
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
                "session_id": target.magi_session_id,
            }
        )
        return DeliveryReceipt(
            channel_id=target.channel_type,
            external_message_id=None,
            delivered_at_ms=0,
            magi_session_id=target.magi_session_id,
        )


class _RecordingTelegramChannel(Channel):
    """Telegram-like channel: non-streaming. Only receives assembled
    content via deliver() from the coordinator's final fanout path.

    DeliveryRouter.fanout_chunk skips channels with supports_streaming=False
    (the SDK default), so this stub never sees streaming chunks — matching
    the production Telegram plugin's intent (Telegram has no native
    streaming UX; double-delivery would result if it processed chunks).
    """

    # supports_streaming inherits the SDK default of False — DO NOT opt in.

    def __init__(self) -> None:
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

    # deliver_chunk intentionally NOT overridden — SDK default raises
    # NotImplementedError, but DeliveryRouter's supports_streaming gate
    # prevents that from being called.

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


class _FakeExecutionOutcome:
    def __init__(self, result: ExecutionResult, *, used_graph: bool = True) -> None:
        self.result = result
        self.used_graph = used_graph


class _FakeExecutionEngine:
    def __init__(self, result: ExecutionResult, *, used_graph: bool = True) -> None:
        self.result = result
        self.used_graph = used_graph
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return _FakeExecutionOutcome(self.result, used_graph=self.used_graph)


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
    """Construct a coordinator wired with the channel delivery dispatcher."""

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
        delivery_dispatcher=ChatDeliveryDispatcher.from_registry(
            channel_registry=_StubRegistry(channels),
            user_prefs_provider=prefs_provider,
        ),
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
    # All targets reached the SSE channel under the scheme key with the
    # per-run session id riding on the dedicated magi_session_id field.
    assert all(t.channel_type == "chat_sse" for t, _ in sse.chunks)
    assert all(t.magi_session_id == "s1" for t, _ in sse.chunks)
    # The trace-store stub (what the chat UI polls) saw all 4.
    assert len(sse.trace_records) == 4
    assert sse.trace_records[-1]["is_final"] is True

    # --- telegram assertions ---
    # Telegram has supports_streaming=False, so DeliveryRouter.fanout_chunk
    # SKIPS it during streaming. The chat_sse stream is unaffected; Telegram
    # will only see the assembled message later via fanout_deliver (covered
    # in test C below).
    assert tg.delivers == []


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
    # Telegram untouched (and also not in the prefs).
    assert tg.delivers == []


# ---------------------------------------------------------------------------
# Test B: final-fanout path via durable postprocess delivery
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
async def test_postprocess_fanout_calls_deliver_on_both_channels() -> None:
    """Execution defers delivery; postprocess fans out the durable result.

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

    # Stub the execution engine so execute() short-circuits with a
    # canned ExecutionResult — same pattern as Task 9's integration tests.
    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="hello world",
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

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

    # No target is sent the answer before persistence.
    assert len(sse.delivers) == 0
    assert len(tg.delivers) == 0

    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(text=result.response_text),
    )

    assert len(sse.delivers) == 1
    assert len(tg.delivers) == 1
    tg_target, tg_content = tg.delivers[0]
    assert tg_content.text == "hello world"
    assert tg_target.channel_type == "telegram"
    # Phase G+2: resolve_delivery_targets leaves external_chat_id empty for
    # non-SSE channels; the channel itself looks up its external id at deliver
    # time using magi_session_id / magi_user_id.
    assert tg_target.external_chat_id == ""
    assert tg_target.magi_session_id == "s1"
    assert tg_target.magi_user_id == "u1"


# ---------------------------------------------------------------------------
# Test C: streaming + final fanout composed together (full e2e)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_chunks_then_final_fanout_reaches_both_channels() -> None:
    """A streamed desktop turn sends only its durable final to Telegram.

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

    coordinator._execution_engine = _FakeExecutionEngine(canned_result)
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
    result = await coordinator.execute(request)

    assert len(sse.delivers) == 0
    assert len(tg.delivers) == 0
    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(text=result.response_text),
        exclude_chat_sse=True,
    )

    # chat_sse already rendered 4 chunks and is excluded from final delivery.
    assert len(sse.chunks) == 4
    assert len(sse.delivers) == 0

    # telegram (supports_streaming=False): NO chunks, only the assembled
    # deliver from the final fanout — no double-send.
    assert len(tg.delivers) == 1
    assert tg.delivers[0][1].text == "hello world"
