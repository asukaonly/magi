"""Phase G+3: coordinator persists DeliveryReceipts via the dedicated store,
not by mutating snapshot.node_states."""

from __future__ import annotations

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.handlers import (
    ChatRuntimeContext,
    ExecutionHandlerRegistry,
    ExecutionMode,
    UserMessagePayload,
)
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.handlers.contracts import IntentDecision
from magi.chat.task_agent.fact_classifier import (
    ChatFactClassifier,
    IncomingFactKind,
)
from magi.chat.task_agent.run_store import SessionRunStore
from magi.agent.task_agents.common.contracts import (
    ExecutionRequest,
    ExecutionResult,
    ToolSelection,
)
from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi.events.events import EventTypes
from magi.tools.context_routing import RouteDecision

from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt


# ---------------------------------------------------------------------------
# Stubs (real Channel + recording receipts store)
# ---------------------------------------------------------------------------


class _RecordingReceiptsStore:
    def __init__(self) -> None:
        self.saves: list[tuple[str, str, int, list]] = []

    async def save_receipts(self, *, session_id, run_id, revision, receipts):
        self.saves.append((session_id, run_id, int(revision), list(receipts)))

    async def list_receipts(self, **kw):
        return []

    async def clear_receipts(self, **kw):
        return None


class _RecordingSseChannel(Channel):
    supports_streaming = True

    def __init__(self) -> None:
        self.delivers: list[tuple[ChannelTarget, DeliveryContent]] = []

    @property
    def channel_type(self) -> str:
        return "chat_sse"

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
        return None

    async def deliver(
        self, target: ChannelTarget, content: DeliveryContent
    ) -> DeliveryReceipt:
        self.delivers.append((target, content))
        return DeliveryReceipt(
            channel_id=target.channel_type,
            external_message_id=None,
            delivered_at_ms=0,
            magi_session_id=target.magi_session_id,
        )


class _StubRegistry:
    def __init__(self, channels: dict[str, Channel]) -> None:
        self._channels = channels

    def get(self, key: str) -> Channel | None:
        return self._channels.get(key)


class _FakeToolRegistry:
    def list_tools(self) -> list[str]:
        return []


class _FakeContextDecider:
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


async def _two_channel_prefs(_user_id: str) -> dict:
    return {"delivery_channels": ["chat_sse"]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postprocess_delivery_writes_receipts_to_store_not_snapshot():
    """Durable postprocess delivery persists receipts outside run snapshots."""
    sse = _RecordingSseChannel()

    class _TgChannel(_RecordingSseChannel):
        @property
        def channel_type(self) -> str:
            return "telegram"

    tg = _TgChannel()
    receipts_store = _RecordingReceiptsStore()
    session_run_store = SessionRunStore()

    async def _prefs(_user_id: str) -> dict:
        return {"delivery_channels": ["chat_sse", "telegram"]}

    decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=[],
            reasoning="",
        )
    )
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        session_run_store=session_run_store,
        delivery_dispatcher=ChatDeliveryDispatcher.from_registry(
            channel_registry=_StubRegistry({"chat_sse": sse, "telegram": tg}),
            user_prefs_provider=_prefs,
            receipts_store=receipts_store,
        ),
    )

    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="hello world",
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

    route = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    )
    context = _build_context_with_run_id(
        user_id="u1", session_id="s1", run_id="run-1",
    )
    context.session_run_revision = 3
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

    # Execution itself does not send before the matching chat outcome exists.
    assert sse.delivers == []
    assert tg.delivers == []
    assert receipts_store.saves == []

    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(text=result.response_text),
    )

    assert len(sse.delivers) == 1
    assert len(tg.delivers) == 1
    # Receipts went to the store, not the snapshot.
    assert len(receipts_store.saves) == 1
    sid, rid, rev, receipts = receipts_store.saves[0]
    assert sid == "s1"
    assert rid == "run-1"
    assert rev == 3
    assert len(receipts) == 2

    # Snapshot must NOT carry delivery_receipts anymore.
    stored_snap = session_run_store.get_run_snapshot("s1", "run-1")
    if stored_snap is not None:
        for state in (stored_snap.node_states or {}).values():
            assert "delivery_receipts" not in state


def test_attach_receipts_helper_is_deleted():
    """The snapshot-mutation helper is gone — receipts now go to the store."""
    from magi.chat.task_agent import coordinator as coord_mod
    assert not hasattr(coord_mod, "_attach_receipts")
