from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.types import TaskAgentType
from magi.chat.task_agent.postprocess.constants import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.chat.task_agent import chat_task_agent as chat_task_agent_module
from magi.chat.task_agent import session_control as session_control_module
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent, _format_llm_error
from magi.agent.task_agents.common import IncomingFactKind
from magi.chat import ChatStore
from magi.chat.contracts import CHAT_DELIVERY_STATE_QUEUED
from magi.control.run_control import DetachSignal, null_run_control
from magi.events.contracts import RuntimeCommandType, UserMessageCommand
from magi.events.events import EventTypes
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


class _PausedPipelineChatAgent(ChatTaskAgent):
    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.batch_taken = asyncio.Event()
        self.release_batch = asyncio.Event()
        self.stage_turn_ids: dict[str, list[str]] = {
            "context": [],
            "admission": [],
            "capabilities": [],
            "request": [],
            "execution": [],
            "finalization": [],
        }

    @staticmethod
    def _turn_id_from_fact(fact: FactRecord | None) -> str:
        if fact is None:
            return ""
        return str(fact.payload.get("turn_id") or "")

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self.batch_taken.set()
        await self.release_batch.wait()
        return await super().merge_facts(new_facts)

    @asynccontextmanager
    async def execution_scope(self, context):  # type: ignore[no-untyped-def]
        """Keep this pipeline-stage test double independent of run admission."""
        _ = context
        yield

    async def build_context(self, merged_facts):  # type: ignore[no-untyped-def]
        turn_id = self._turn_id_from_fact(merged_facts[-1] if merged_facts else None)
        self.stage_turn_ids["context"].append(turn_id)
        return SimpleNamespace(latest_fact=merged_facts[-1])

    async def admit_context(self, context):  # type: ignore[no-untyped-def]
        self.stage_turn_ids["admission"].append(self._turn_id_from_fact(context.latest_fact))
        return object()

    async def resolve_capabilities(self, context, admission):  # type: ignore[no-untyped-def]
        _ = admission
        self.stage_turn_ids["capabilities"].append(self._turn_id_from_fact(context.latest_fact))
        return object()

    async def build_execution_request(  # type: ignore[no-untyped-def]
        self,
        context,
        admission,
        capabilities,
    ):
        _ = (admission, capabilities)
        self.stage_turn_ids["request"].append(self._turn_id_from_fact(context.latest_fact))
        return object()

    async def execute_request(self, context, request):  # type: ignore[no-untyped-def]
        _ = request
        self.stage_turn_ids["execution"].append(self._turn_id_from_fact(context.latest_fact))
        return object()

    async def finalize_result(self, context, result):  # type: ignore[no-untyped-def]
        _ = result
        self.stage_turn_ids["finalization"].append(self._turn_id_from_fact(context.latest_fact))


class _PostCheckPausedChatAgent(ChatTaskAgent):
    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.preliminary_check_passed = asyncio.Event()
        self.release_after_check = asyncio.Event()

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        merged = await super().merge_facts(new_facts)
        self.preliminary_check_passed.set()
        await self.release_after_check.wait()
        return merged


class _AroutePausedChatAgent(ChatTaskAgent):
    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.final_check_passed = asyncio.Event()
        self.release_run_admission = asyncio.Event()
        self.run_admitted = asyncio.Event()
        self.cancellation_committed = asyncio.Event()
        self.context_load_calls = 0

    async def _before_execution_run_admission(
        self,
        *,
        classified,
    ) -> None:  # type: ignore[no-untyped-def]
        _ = classified
        self.final_check_passed.set()
        await self.release_run_admission.wait()

    async def _after_execution_run_admitted(
        self,
        *,
        classified,
        run_decision,
    ) -> None:  # type: ignore[no-untyped-def]
        _ = (classified, run_decision)
        self.run_admitted.set()

    async def _load_context_inputs(
        self,
        classified,
        run_decision,
    ):  # type: ignore[no-untyped-def]
        _ = run_decision
        self.context_load_calls += 1
        await self.cancellation_committed.wait()
        return SimpleNamespace(
            session_id=classified.session_id,
            active_persona_id=None,
            history_context=SimpleNamespace(
                session_summary=None,
                session_origin="chat",
            ),
            history=[],
            history_key=f"{classified.user_id}:{classified.session_id}",
            recent_tool_errors=[],
            recent_tool_state=[],
            reply_context=None,
            recall_feedback=None,
            preferences=SimpleNamespace(
                streaming_chat_enabled=False,
                allow_media_grounding_for_conversation=False,
                core_model_supports_vision=False,
                core_model_supports_tool_calls=True,
            ),
        )


def _user_fact(content: str, *, turn_id: str) -> FactRecord:
    return FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "content": content,
            "turn_id": turn_id,
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id=f"corr-{turn_id}",
    )


async def _create_admitted_turn(
    chat_store: ChatStore,
    *,
    session_id: str,
    user_id: str,
    turn_id: str,
    command_id: int,
) -> None:
    await chat_store.create_user_turn(
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        message_text=f"message for {turn_id}",
        created_at_ms=1710000000000 + command_id,
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id=turn_id,
        delivery_attempt_no=0,
        command_id=command_id,
        updated_at_ms=1710000001000 + command_id,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id=turn_id,
        delivery_attempt_no=0,
        command_id=command_id,
        updated_at_ms=1710000002000 + command_id,
    )


def _tool_loop_fact(*, revision: int = 0) -> FactRecord:
    return FactRecord(
        agent_id="chat:u-chat",
        event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "stage": "tool_result",
            "response_preview": "tool checkpoint",
            "run_revision": revision,
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id=f"tool-{revision}",
    )


def test_chat_task_agent_streaming_enabled_reads_streaming_preference(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_get_user_preference(key: str, default: object = None) -> object:
        calls.append((key, default))
        return False

    monkeypatch.setattr(chat_task_agent_module, "get_user_preference", fake_get_user_preference)
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    assert agent._streaming_enabled("u-chat") is False
    assert calls == [("streaming_chat_enabled", False)]


def test_chat_task_agent_disables_streaming_when_rhythm_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        chat_task_agent_module,
        "get_user_preference",
        lambda key, default=None: True if key == "streaming_chat_enabled" else default,
    )
    monkeypatch.setattr(chat_task_agent_module, "is_conversation_rhythm_enabled", lambda: True)
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    assert agent._streaming_enabled("u-chat") is False


def test_chat_task_agent_reports_postprocess_retry_as_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    monkeypatch.setattr(
        agent._postprocess_service,
        "has_pending_background_work",
        lambda: True,
    )

    assert agent.has_inflight_work() is True


@pytest.mark.asyncio
async def test_chat_task_agent_routes_each_queued_user_message_independently() -> None:
    routed_turns: list[str] = []
    admitted_turns: list[str] = []
    response_turns: list[str] = []
    routed_batches: list[list[str]] = []

    class _TrackingChatTaskAgent(ChatTaskAgent):
        async def build_context(self, merged_facts):  # type: ignore[no-untyped-def]
            _ = merged_facts
            batch_facts = list(self._last_batch_facts)
            assert sum(fact.event_type == EventTypes.USER_MESSAGE for fact in batch_facts) == 1
            routed_batches.append([fact.event_type for fact in batch_facts])
            latest_fact = batch_facts[-1]
            classified = self._fact_classifier.classify(
                agent_id=self.agent_id,
                latest_fact=latest_fact,
                batch_facts=batch_facts,
            )
            decision = await self._session_run_coordinator.aroute(classified)
            assert classified.latest_user_payload is not None
            turn_id = classified.latest_user_payload.turn_id
            routed_turns.append(turn_id)
            return SimpleNamespace(turn_id=turn_id, decision=decision)

        async def admit_context(self, context):  # type: ignore[no-untyped-def]
            admitted_turns.append(context.turn_id)
            return object()

        async def resolve_capabilities(self, context, admission):  # type: ignore[no-untyped-def]
            _ = (context, admission)
            return object()

        async def build_execution_request(  # type: ignore[no-untyped-def]
            self,
            context,
            admission,
            capabilities,
        ):
            _ = (admission, capabilities)
            return context

        async def execute_request(self, context, request):  # type: ignore[no-untyped-def]
            _ = context
            return request

        async def finalize_result(self, context, result) -> None:  # type: ignore[no-untyped-def]
            _ = result
            response_turns.append(context.turn_id)

    agent = _TrackingChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
    )
    for index in range(1, 4):
        assert await agent.add_fact(_user_fact(f"message {index}", turn_id=f"turn-{index}"))
        if index < 3:
            assert await agent.add_fact(
                FactRecord(
                    agent_id="chat:u-chat",
                    agent_type=TaskAgentType.CHAT.value,
                    agent_instance_id="u-chat",
                    event_type="SENSOR_CONTEXT_UPDATED",
                    payload={"content": f"sensor context {index}"},
                )
            )
    assert agent._fact_queue.qsize() == 5

    await agent.start(event_emitter=None)
    try:
        for _ in range(100):
            if agent.get_stats()["processed"] == 5:
                break
            await asyncio.sleep(0.01)
        expected = ["turn-1", "turn-2", "turn-3"]
        assert routed_turns == expected
        assert admitted_turns == expected
        assert response_turns == expected
        assert routed_batches == [
            [EventTypes.USER_MESSAGE, "SENSOR_CONTEXT_UPDATED"],
            [EventTypes.USER_MESSAGE, "SENSOR_CONTEXT_UPDATED"],
            [EventTypes.USER_MESSAGE],
        ]
    finally:
        await agent.stop()


@pytest.mark.asyncio
async def test_chat_batch_boundary_keeps_later_user_queued_across_stop() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    leading_context = FactRecord(
        agent_id="chat:u-chat",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="u-chat",
        event_type="SENSOR_CONTEXT_UPDATED",
        payload={"content": "leading context"},
    )
    trailing_context = FactRecord(
        agent_id="chat:u-chat",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="u-chat",
        event_type="SENSOR_CONTEXT_UPDATED",
        payload={"content": "trailing context"},
    )
    first_user = _user_fact("first", turn_id="turn-first")
    second_user = _user_fact("second", turn_id="turn-second")
    for fact in (leading_context, first_user, trailing_context, second_user):
        assert await agent.add_fact(fact)

    first_batch = await agent._take_next_batch()
    assert first_batch == [leading_context, first_user, trailing_context]
    assert agent._fact_queue.snapshot() == (second_user,)
    assert agent._facts_available.is_set()

    await agent.stop()

    assert agent._fact_queue.snapshot() == (second_user,)
    second_batch = await agent._take_next_batch()
    assert second_batch == [second_user]
    assert agent._fact_queue.empty()
    assert not agent._facts_available.is_set()


@pytest.mark.asyncio
async def test_chat_task_agent_uses_injected_chat_read_service_for_workspace() -> None:
    class _FakeSessionSummary:
        workspace_path = "/tmp/magi-workspace"

    class _FakeReadService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def aget_session_summary(self, user_id: str, session_id: str):
            self.calls.append((user_id, session_id))
            return _FakeSessionSummary()

    read_service = _FakeReadService()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        chat_read_service_factory=lambda: read_service,
    )

    workspace_path = await agent._resolve_session_workspace_path(
        user_id="u-chat", session_id="s-chat"
    )

    assert workspace_path == "/tmp/magi-workspace"
    assert read_service.calls == [("u-chat", "s-chat")]


@pytest.mark.asyncio
async def test_chat_task_agent_prefers_user_fact_over_tool_loop_trace_in_mixed_batch() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    user_fact = _user_fact("Help me inspect the login flow.", turn_id="turn-1")
    tool_loop_fact = _tool_loop_fact()

    merged = await agent.merge_facts([user_fact, tool_loop_fact])
    context = await agent.build_context(merged)
    decision = await agent.admit_context(context)

    assert context.latest_fact == tool_loop_fact
    assert context.planner_fact == user_fact
    assert context.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert context.latest_user_message == "Help me inspect the login flow."
    assert decision.execution_mode is None


# ---------------------------------------------------------------------------
# _format_llm_error helpers
# ---------------------------------------------------------------------------


class _FakeRateLimitError(Exception):
    def __init__(self) -> None:
        super().__init__("Error code: 429 - {'error': {'code': '1302', 'message': '速率限制'}}")
        self.status_code = 429


class _FakeAuthError(Exception):
    def __init__(self) -> None:
        super().__init__("Error code: 401 - Unauthorized")
        self.status_code = 401


class _FakeServerError(Exception):
    def __init__(self) -> None:
        super().__init__("Error code: 503 - Service Unavailable")
        self.status_code = 503


def test_format_llm_error_rate_limit() -> None:
    msg = _format_llm_error(_FakeRateLimitError())
    assert "rate" in msg.lower() or "限" in msg


def test_format_llm_error_auth() -> None:
    msg = _format_llm_error(_FakeAuthError())
    assert "auth" in msg.lower() or "api key" in msg.lower()


def test_format_llm_error_server() -> None:
    msg = _format_llm_error(_FakeServerError())
    assert "unavailable" in msg.lower() or "later" in msg.lower()


def test_format_llm_error_generic() -> None:
    msg = _format_llm_error(ValueError("something went wrong"))
    assert "ValueError" in msg


def test_format_llm_error_task_budget() -> None:
    from magi.agent.execution.task_budget import TaskBudgetExceeded

    msg = _format_llm_error(
        TaskBudgetExceeded(resource="llm_calls", limit=30, used=30, requested=1)
    )

    assert "execution limit" in msg
    assert "AI service" not in msg


# ---------------------------------------------------------------------------
# request execution emits an error stream chunk on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_request_emits_error_chunk_on_failure(monkeypatch) -> None:
    """When request execution raises, the agent still returns a terminal result.

    The result goes through the normal postprocess path so the session run can
    be finalized instead of leaving the turn stuck in `running`.
    """
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    monkeypatch.setattr(
        chat_task_agent_module,
        "get_user_preference",
        lambda key, default=None: key == "streaming_chat_enabled",
    )
    monkeypatch.setattr(chat_task_agent_module, "is_conversation_rhythm_enabled", lambda: False)

    emitted: list[dict] = []

    async def _fake_emit(*, event, user_id, session_id, turn_id, **_kwargs):
        emitted.append({"kind": event.kind, "text": event.text})

    monkeypatch.setattr(agent, "_emit_stream_event", _fake_emit)

    class _FakeCoordinator:
        async def execute_request(self, _request):
            raise _FakeRateLimitError()

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind

    ctx = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="u-chat",
        agent_type="chat",
        runtime_key="chat:u-chat",
        user_id="u-chat",
        session_id="s-test",
        history_key="u-chat:s-test",
        history=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=SimpleNamespace(turn_id="turn-x"),
        conversation_history=[],
    )

    result = await agent.execute_request(ctx, SimpleNamespace(mode=None))

    assert len(emitted) == 2
    assert emitted[0]["kind"] == "text_delta"
    assert "rate" in emitted[0]["text"].lower()
    assert emitted[1]["kind"] == "text_flush"
    assert result.response_text == emitted[0]["text"]
    assert result.streamed is True


@pytest.mark.asyncio
async def test_execute_request_does_not_emit_error_chunk_when_streaming_disabled(
    monkeypatch,
) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    monkeypatch.setattr(
        chat_task_agent_module,
        "get_user_preference",
        lambda key, default=None: False,
    )

    emitted: list[dict] = []

    async def _fake_emit(**kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(agent, "_emit_stream_event", _fake_emit)

    class _FakeCoordinator:
        async def execute_request(self, _request):
            raise _FakeRateLimitError()

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind

    ctx = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="u-chat",
        agent_type="chat",
        runtime_key="chat:u-chat",
        user_id="u-chat",
        session_id="s-test",
        history_key="u-chat:s-test",
        history=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=SimpleNamespace(turn_id="turn-x"),
        conversation_history=[],
    )

    result = await agent.execute_request(ctx, SimpleNamespace(mode=None))

    assert emitted == []
    assert "rate" in result.response_text.lower()
    assert result.streamed is False


@pytest.mark.asyncio
async def test_execute_request_skips_emit_when_no_turn_id(monkeypatch) -> None:
    """If turn_id is missing, no stream chunk is emitted (avoids noisy errors)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    emitted: list[dict] = []

    async def _fake_emit(**kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(agent, "_emit_stream_event", _fake_emit)

    class _FakeCoordinator:
        async def execute_request(self, _request):
            raise RuntimeError("boom")

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind

    ctx = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="u-chat",
        agent_type="chat",
        runtime_key="chat:u-chat",
        user_id="u-chat",
        session_id="s-test",
        history_key="u-chat:s-test",
        history=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=SimpleNamespace(turn_id=""),
        conversation_history=[],
    )

    result = await agent.execute_request(ctx, SimpleNamespace(mode=None))

    assert emitted == []
    assert "RuntimeError" in result.response_text
    assert result.streamed is False


@pytest.mark.asyncio
async def test_failed_llm_turn_is_finalized_before_next_user_message(monkeypatch) -> None:
    """A failed first turn must not leave the active run open for turn two.

    Regression: when request execution re-raised, `TaskAgent._run_loop`
    swallowed the exception before finalization, so `ChatPostProcessService` never
    called `complete_session_run(...)`. The next user message then revised the
    old run instead of starting a fresh one.
    """
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    class _FakeEmitter:
        async def emit_chat_response_event(self, **kwargs):  # type: ignore[no-untyped-def]
            return None

    class _FakeCoordinator:
        async def execute_request(self, _request):
            raise RuntimeError("boom")

    agent._event_emitter = _FakeEmitter()  # type: ignore[assignment]
    agent._coordinator = _FakeCoordinator()

    first_fact = _user_fact("你是谁", turn_id="turn-1")
    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    assert first_context.session_run_id is not None

    result = await agent.execute_request(
        first_context,
        SimpleNamespace(mode=None),
    )
    await agent.finalize_result(first_context, result)

    # The failed turn is fully finalized, so there is no active run left.
    assert agent._session_run_coordinator.get_active_run("s-chat") is None

    second_fact = _user_fact("你到底是谁", turn_id="turn-2")
    second_context = await agent.build_context(await agent.merge_facts([second_fact]))

    # The second message starts a fresh run rather than revising turn-1.
    assert second_context.session_run_id is not None
    assert second_context.session_run_id != first_context.session_run_id
    assert second_context.active_run is not None
    assert second_context.active_run.root_turn_id == "turn-2"


@pytest.mark.asyncio
async def test_add_fact_strict_cancel_requests_cancel_on_active_run() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # Prime an active run as if a turn is in flight.
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )
    assert agent._session_run_coordinator.get_active_run("s-chat").status == "running"

    # Enqueue a fact whose normalized form exactly equals a cancel phrase.
    cancel_fact = _user_fact("Stop!", turn_id="turn-cancel")
    enqueued = await agent.add_fact(cancel_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    assert active_run.status == "cancelling"
    assert active_run.cancel_requested_by == "user"
    assert active_run.cancel_reason == "user_cancel"
    assert active_run.cancel_anchor_turn_id == "turn-1"
    assert agent._fact_queue.empty()


@pytest.mark.asyncio
async def test_add_fact_strict_cancel_accepts_chinese_phrase() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )

    cancel_fact = _user_fact("取消！", turn_id="turn-cancel")
    enqueued = await agent.add_fact(cancel_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    assert active_run.status == "cancelling"


@pytest.mark.asyncio
async def test_add_fact_long_message_containing_stop_becomes_run_input() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )

    passing_fact = _user_fact(
        "Please don't stop at the login page, also check the checkout flow.",
        turn_id="turn-passing",
    )
    enqueued = await agent.add_fact(passing_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    # The substring "stop" must not trigger cancellation.
    assert active_run.status == "running"
    assert active_run.cancel_requested_by is None
    assert [item.turn_id for item in active_run.pending_turns] == ["turn-passing"]
    assert agent._fact_queue.empty()


@pytest.mark.asyncio
async def test_add_fact_ordinary_message_queues_active_run_input() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )

    input_fact = _user_fact("Also, include the staging endpoint.", turn_id="turn-input")
    enqueued = await agent.add_fact(input_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    assert active_run.status == "running"
    assert active_run.cancel_requested_by is None
    assert [(item.turn_id, item.disposition) for item in active_run.pending_turns] == [
        ("turn-input", "message")
    ]
    assert agent._fact_queue.empty()


@pytest.mark.asyncio
async def test_strict_cancel_text_is_an_ordinary_root_without_active_run() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    # No active run exists; the ingress fast-path must stay silent and
    # simply enqueue the fact.
    cancel_fact = _user_fact("stop", turn_id="turn-only")
    enqueued = await agent.add_fact(cancel_fact)

    assert enqueued is True
    assert agent._session_run_coordinator.get_active_run("s-chat") is None


@pytest.mark.asyncio
async def test_rejected_managed_cancel_does_not_cancel_active_run() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-root",
            source="api",
        )  # type: ignore[arg-type]
    )

    admission = await agent.add_fact_with_admission(
        _user_fact("Stop!", turn_id="turn-stale-stop"),
        admit=lambda: asyncio.sleep(0, result=False),
    )

    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert admission.superseded is True
    assert active_run is not None
    assert active_run.status == "running"
    assert agent._fact_queue.empty()


@pytest.mark.asyncio
async def test_strict_cancel_waits_for_run_admission_boundary() -> None:
    agent = _AroutePausedChatAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
    )
    agent.cancellation_committed.set()
    root_fact = _user_fact("Inspect the login flow.", turn_id="turn-root")
    merged = await agent.merge_facts([root_fact])
    build_task = asyncio.create_task(agent.build_context(merged))
    cancel_task: asyncio.Task[bool] | None = None

    try:
        await asyncio.wait_for(agent.final_check_passed.wait(), timeout=1.0)
        cancel_task = asyncio.create_task(
            agent.add_fact(_user_fact("Stop!", turn_id="turn-cancel"))
        )
        await asyncio.sleep(0)
        assert not cancel_task.done()

        agent.release_run_admission.set()
        context = await asyncio.wait_for(build_task, timeout=1.0)
        assert await asyncio.wait_for(cancel_task, timeout=1.0)

        active_run = agent._session_run_coordinator.get_active_run("s-chat")
        assert active_run is not None
        assert active_run.run_id == context.session_run_id
        assert active_run.status == "cancelling"
        assert active_run.cancel_anchor_turn_id == "turn-root"
        assert agent._fact_queue.empty()
    finally:
        agent.release_run_admission.set()
        if cancel_task is not None and not cancel_task.done():
            cancel_task.cancel()
        if not build_task.done():
            build_task.cancel()


@pytest.mark.asyncio
async def test_detach_waits_for_run_admission_and_targets_admitted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _AroutePausedChatAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
    )
    agent.cancellation_committed.set()
    detach_signal = DetachSignal()

    async def _bind_detach_signal(
        *,
        classified,
        run_decision,
    ) -> None:  # type: ignore[no-untyped-def]
        agent._session_run_coordinator.bind_detach_signal(
            classified.session_id,
            detach_signal,
        )
        agent.run_admitted.set()

    async def _ignore_control_notification(**_kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        agent,
        "_after_execution_run_admitted",
        _bind_detach_signal,
    )
    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _ignore_control_notification,
    )
    root_fact = _user_fact("Inspect the login flow.", turn_id="turn-root")
    merged = await agent.merge_facts([root_fact])
    build_task = asyncio.create_task(agent.build_context(merged))
    detach_task: asyncio.Task[dict[str, object] | None] | None = None

    try:
        await asyncio.wait_for(agent.final_check_passed.wait(), timeout=1.0)
        detach_task = asyncio.create_task(
            agent.request_session_detach(
                session_id="s-chat",
                requested_by="user",
                anchor_turn_id="turn-root",
            )
        )
        await asyncio.sleep(0)
        assert not detach_task.done()

        agent.release_run_admission.set()
        context = await asyncio.wait_for(build_task, timeout=1.0)
        result = await asyncio.wait_for(detach_task, timeout=1.0)

        assert result is not None
        assert result["run_id"] == context.session_run_id
        assert detach_signal.is_requested()
        active_run = agent._session_run_coordinator.get_active_run("s-chat")
        assert active_run is not None
        assert active_run.run_id == context.session_run_id
    finally:
        agent.release_run_admission.set()
        if detach_task is not None and not detach_task.done():
            detach_task.cancel()
        if not build_task.done():
            build_task.cancel()


@pytest.mark.asyncio
async def test_session_cancel_uses_shared_pending_input_release_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator._run_store.create_active_run(
        "s-chat",
        root_turn_id="turn-root",
        root_user_message="Finish the root task",
        run_id="run-root",
    )
    agent._session_run_coordinator._run_store.append_pending_turn(
        "s-chat",
        "turn-input",
        "Handle this after the root task",
    )
    barrier_calls: list[tuple[str, str, int, list[str]]] = []
    cancellation_order: list[str] = []

    async def _cancel_run(**_kwargs):  # type: ignore[no-untyped-def]
        cancellation_order.append("worker_cancel")
        return []

    async def _persist_cancel(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        cancellation_order.append("durable_cancel")
        return True

    async def _checkpoint_and_release(
        *,
        session_id: str,
        run_id: str,
        revision: int,
        pending_inputs: list,
    ) -> bool:
        barrier_calls.append(
            (
                session_id,
                run_id,
                revision,
                [turn.turn_id for turn in pending_inputs],
            )
        )
        return True

    async def _emit_control(**_kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        agent,
        "_mark_session_turn_cancelled",
        _persist_cancel,
    )
    monkeypatch.setattr(session_control_module, "_cancel_child_runs", _cancel_run)
    monkeypatch.setattr(
        agent._postprocess_service,
        "release_pending_inputs_after_run_completion",
        _checkpoint_and_release,
    )
    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _emit_control,
    )

    await agent.request_session_cancel(
        session_id="s-chat",
        requested_by="user",
    )

    assert barrier_calls == [("s-chat", "run-root", 0, ["turn-input"])]
    assert cancellation_order == ["durable_cancel", "worker_cancel"]


@pytest.mark.asyncio
async def test_session_cancel_is_durable_before_worker_shutdown(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-root",
        message_text="Finish the root task",
        created_at_ms=1710000000000,
        run_id="run-root",
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id="turn-root",
        delivery_attempt_no=0,
        command_id=501,
        updated_at_ms=1710000000001,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id="turn-root",
        delivery_attempt_no=0,
        command_id=501,
        updated_at_ms=1710000000002,
    )
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        "s-chat",
        root_turn_id="turn-root",
        root_user_message="Finish the root task",
        run_id="run-root",
    )
    worker_cancel_calls: list[str] = []

    async def _cancel_run(**_kwargs):  # type: ignore[no-untyped-def]
        turn = await chat_store.get_turn("turn-root")
        delivery = await chat_store.get_user_turn_delivery(turn_id="turn-root")
        assert turn is not None
        assert turn.status == "cancelled"
        assert delivery is not None
        assert delivery.delivery_state == "terminal"
        worker_cancel_calls.append("cancelled")
        return []

    async def _checkpoint_and_release(**_kwargs):  # type: ignore[no-untyped-def]
        return True

    async def _emit_control(**_kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(session_control_module, "_cancel_child_runs", _cancel_run)
    monkeypatch.setattr(
        agent._postprocess_service,
        "release_pending_inputs_after_run_completion",
        _checkpoint_and_release,
    )
    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _emit_control,
    )

    result = await agent.request_session_cancel(
        session_id="s-chat",
        requested_by="user",
    )

    assert result is not None
    assert worker_cancel_calls == ["cancelled"]


@pytest.mark.asyncio
async def test_pre_admission_cancel_rejects_wrong_owner(
    runtime_paths_with_schema,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-owner",
        user_id="u-owner",
        turn_id="turn-owner",
        message_text="Keep this turn",
        created_at_ms=1710000000000,
    )
    agent = ChatTaskAgent(
        agent_id="s-owner",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )

    wrong_session = await agent.request_session_cancel(
        session_id="s-other",
        user_id="u-owner",
        requested_by="user",
        anchor_turn_id="turn-owner",
    )
    wrong_user = await agent.request_session_cancel(
        session_id="s-owner",
        user_id="u-other",
        requested_by="user",
        anchor_turn_id="turn-owner",
    )

    turn = await chat_store.get_turn("turn-owner")
    delivery = await chat_store.get_user_turn_delivery(turn_id="turn-owner")
    assert wrong_session is None
    assert wrong_user is None
    assert turn is not None
    assert turn.status == "queued"
    assert delivery is not None
    assert delivery.delivery_state == "ready"


@pytest.mark.asyncio
async def test_cancelled_admitted_turn_is_removed_from_agent_queue(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-cancel-queued-fact",
        message_text="Cancel this queued fact",
        created_at_ms=1710000000000,
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id="turn-cancel-queued-fact",
        delivery_attempt_no=0,
        command_id=903,
        updated_at_ms=1710000000001,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id="turn-cancel-queued-fact",
        delivery_attempt_no=0,
        command_id=903,
        updated_at_ms=1710000000002,
    )
    agent = ChatTaskAgent(
        agent_id="s-chat",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )
    target_fact = _user_fact(
        "Cancel this queued fact",
        turn_id="turn-cancel-queued-fact",
    )
    target_fact.delivery_attempt_no = 0
    target_fact.runtime_command_id = 903
    sibling_fact = _user_fact("Keep this queued fact", turn_id="turn-sibling")
    assert await agent.add_fact(target_fact)
    assert await agent.add_fact(sibling_fact)

    async def _ignore_control_notification(**_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _ignore_control_notification,
    )
    result = await agent.request_session_cancel(
        session_id="s-chat",
        user_id="u-chat",
        requested_by="user",
        anchor_turn_id="turn-cancel-queued-fact",
    )

    queued_turn_ids = [
        str(fact.payload.get("turn_id") or "") for fact in agent.snapshot_inflight_facts()
    ]
    assert result is not None
    assert result["status"] == "cancelled"
    assert queued_turn_ids == ["turn-sibling"]


@pytest.mark.asyncio
async def test_cancelled_active_batch_stops_before_any_execution_stage(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    created = await chat_store.create_user_turn_once(
        session_id="s-active-batch",
        user_id="u-active-batch",
        turn_id="turn-active-batch",
        message_text="Stop before execution",
        created_at_ms=1710000000000,
        runtime_envelope={
            "source": "api",
            "user_id": "u-active-batch",
            "session_id": "s-active-batch",
            "turn_id": "turn-active-batch",
            "message": "Stop before execution",
            "attachments": [],
            "workspace_path": None,
            "interaction_kind": None,
            "metadata": {},
            "runtime_namespace": "desktop",
        },
        request_fingerprint="active-batch-cancel-request",
    )
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path),
    )
    await queue.start()
    command_id = await queue.enqueue_user_message(
        UserMessageCommand(
            source="api",
            user_id="u-active-batch",
            session_id="s-active-batch",
            turn_id="turn-active-batch",
            message="Stop before execution",
            correlation_id=f"user_message:{created.message.message_id}",
        )
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id="turn-active-batch",
        delivery_attempt_no=0,
        command_id=command_id,
        updated_at_ms=1710000000001,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id="turn-active-batch",
        delivery_attempt_no=0,
        command_id=command_id,
        updated_at_ms=1710000000002,
    )
    await queue.ack(command_id)

    agent = _PausedPipelineChatAgent(
        agent_id="s-active-batch",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )

    async def _ignore_control_notification(**_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _ignore_control_notification,
    )
    fact = FactRecord(
        agent_id=agent.runtime_key,
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-active-batch",
            "session_id": "s-active-batch",
            "content": "Stop before execution",
            "turn_id": "turn-active-batch",
        },
        agent_type="chat",
        agent_instance_id="s-active-batch",
        correlation_id=f"user_message:{created.message.message_id}",
        delivery_attempt_no=0,
        runtime_command_id=command_id,
    )
    await agent.start(event_emitter=None)
    agent.release_batch.clear()
    try:
        assert await agent.add_fact(fact)
        await asyncio.wait_for(agent.batch_taken.wait(), timeout=1.0)
        assert [
            str(item.payload.get("turn_id") or "") for item in agent.snapshot_inflight_facts()
        ] == ["turn-active-batch"]

        first_cancel = await agent.request_session_cancel(
            session_id="s-active-batch",
            user_id="u-active-batch",
            requested_by="user",
            anchor_turn_id="turn-active-batch",
        )
        repeated_cancel = await agent.request_session_cancel(
            session_id="s-active-batch",
            user_id="u-active-batch",
            requested_by="user",
            anchor_turn_id="turn-active-batch",
        )
        assert first_cancel is not None
        assert repeated_cancel is not None
        agent.release_batch.set()

        for _ in range(100):
            if agent.get_stats()["processed"] == 1:
                break
            await asyncio.sleep(0.01)

        turn = await chat_store.get_turn("turn-active-batch")
        delivery = await chat_store.get_user_turn_delivery(
            turn_id="turn-active-batch",
        )
        assert turn is not None
        assert turn.status == "cancelled"
        assert delivery is not None
        assert delivery.delivery_state == "terminal"
        assert agent.get_stats()["processed"] == 1
        assert all(not turn_ids for turn_ids in agent.stage_turn_ids.values())
        assert agent._fact_memory == []
        assert (await queue.get_stats())["completed_count"] == 1
    finally:
        agent.release_batch.set()
        await agent.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_cancelled_active_batch_keeps_sibling_fact_executable(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await _create_admitted_turn(
        chat_store,
        session_id="s-active-siblings",
        user_id="u-active-siblings",
        turn_id="turn-cancelled-sibling",
        command_id=911,
    )
    await _create_admitted_turn(
        chat_store,
        session_id="s-active-siblings",
        user_id="u-active-siblings",
        turn_id="turn-kept-sibling",
        command_id=912,
    )
    agent = _PausedPipelineChatAgent(
        agent_id="s-active-siblings",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )

    async def _ignore_control_notification(**_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _ignore_control_notification,
    )
    target_fact = FactRecord(
        agent_id=agent.runtime_key,
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-active-siblings",
            "session_id": "s-active-siblings",
            "content": "Cancel only this fact",
            "turn_id": "turn-cancelled-sibling",
        },
        agent_type="chat",
        agent_instance_id="s-active-siblings",
        correlation_id="target-active-sibling",
        delivery_attempt_no=0,
        runtime_command_id=911,
    )
    kept_fact = FactRecord(
        agent_id=agent.runtime_key,
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-active-siblings",
            "session_id": "s-active-siblings",
            "content": "Keep processing this fact",
            "turn_id": "turn-kept-sibling",
        },
        agent_type="chat",
        agent_instance_id="s-active-siblings",
        correlation_id="kept-active-sibling",
        delivery_attempt_no=0,
        runtime_command_id=912,
    )
    assert await agent.add_fact(target_fact)
    assert await agent.add_fact(kept_fact)
    await agent.start(event_emitter=None)
    try:
        await asyncio.wait_for(agent.batch_taken.wait(), timeout=1.0)
        result = await agent.request_session_cancel(
            session_id="s-active-siblings",
            user_id="u-active-siblings",
            requested_by="user",
            anchor_turn_id="turn-cancelled-sibling",
        )
        assert result is not None
        agent.release_batch.set()

        for _ in range(100):
            if agent.get_stats()["processed"] == 2:
                break
            await asyncio.sleep(0.01)

        assert agent.get_stats()["processed"] == 2
        assert agent._fact_memory == [kept_fact]
        assert all(turn_ids == ["turn-kept-sibling"] for turn_ids in agent.stage_turn_ids.values())
    finally:
        agent.release_batch.set()
        await agent.stop()


@pytest.mark.asyncio
async def test_stop_after_preliminary_delivery_check_wins_before_run_creation(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await _create_admitted_turn(
        chat_store,
        session_id="s-post-check",
        user_id="u-post-check",
        turn_id="turn-post-check",
        command_id=921,
    )
    agent = _PostCheckPausedChatAgent(
        agent_id="s-post-check",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )
    forbidden_calls: list[str] = []

    def _forbid_classification(**_kwargs):  # type: ignore[no-untyped-def]
        forbidden_calls.append("classification")
        raise AssertionError("classification must not run")

    async def _forbid_context(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        forbidden_calls.append("context")
        raise AssertionError("context must not load")

    async def _forbid_admission(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        forbidden_calls.append("admission")
        raise AssertionError("context must not be admitted")

    async def _forbid_control_notification(**_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(agent._fact_classifier, "classify", _forbid_classification)
    monkeypatch.setattr(agent, "_load_context_inputs", _forbid_context)
    monkeypatch.setattr(agent._coordinator, "admit_context", _forbid_admission)
    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _forbid_control_notification,
    )
    fact = _user_fact("Stop after the first check", turn_id="turn-post-check")
    fact.payload["user_id"] = "u-post-check"
    fact.payload["session_id"] = "s-post-check"
    fact.delivery_attempt_no = 0
    fact.runtime_command_id = 921

    assert await agent.add_fact(fact)
    await agent.start(event_emitter=None)
    try:
        await asyncio.wait_for(
            agent.preliminary_check_passed.wait(),
            timeout=1.0,
        )
        outcome = await agent.request_session_cancel(
            session_id="s-post-check",
            user_id="u-post-check",
            requested_by="user",
            anchor_turn_id="turn-post-check",
        )
        assert outcome is not None
        assert agent._session_run_coordinator.get_active_run("s-post-check") is None
        agent.release_after_check.set()

        for _ in range(100):
            if agent.get_stats()["processed"] == 1:
                break
            await asyncio.sleep(0.01)

        assert agent.get_stats()["processed"] == 1
        assert forbidden_calls == []
        assert agent._fact_memory == []
        assert agent._session_run_coordinator.get_active_run("s-post-check") is None
    finally:
        agent.release_after_check.set()
        await agent.stop()


@pytest.mark.asyncio
async def test_aroute_winner_is_cancelled_before_tools_or_model(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await _create_admitted_turn(
        chat_store,
        session_id="s-aroute-wins",
        user_id="u-aroute-wins",
        turn_id="turn-aroute-wins",
        command_id=922,
    )
    agent = _AroutePausedChatAgent(
        agent_id="s-aroute-wins",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )
    forbidden_calls: list[str] = []
    original_mark_cancelled = agent._mark_session_turn_cancelled

    async def _mark_and_signal(*args, **kwargs):  # type: ignore[no-untyped-def]
        changed = await original_mark_cancelled(*args, **kwargs)
        if changed:
            agent.cancellation_committed.set()
        return changed

    async def _cancel_workers(**_kwargs):  # type: ignore[no-untyped-def]
        return []

    async def _checkpoint_and_release(**_kwargs):  # type: ignore[no-untyped-def]
        return True

    async def _ignore_control_notification(**_kwargs):  # type: ignore[no-untyped-def]
        return None

    async def _record_admission(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        forbidden_calls.append("admission")
        return object()

    async def _record_capabilities(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        forbidden_calls.append("capabilities")
        return object()

    async def _record_request(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        forbidden_calls.append("request")
        return object()

    async def _record_execution(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        forbidden_calls.append("execution")
        return object()

    monkeypatch.setattr(agent, "_mark_session_turn_cancelled", _mark_and_signal)
    monkeypatch.setattr(session_control_module, "_cancel_child_runs", _cancel_workers)
    monkeypatch.setattr(
        agent._postprocess_service,
        "release_pending_inputs_after_run_completion",
        _checkpoint_and_release,
    )
    monkeypatch.setattr(
        agent._postprocess_service,
        "emit_execution_control_notification",
        _ignore_control_notification,
    )
    monkeypatch.setattr(agent._coordinator, "admit_context", _record_admission)
    monkeypatch.setattr(agent, "resolve_capabilities", _record_capabilities)
    monkeypatch.setattr(agent, "build_execution_request", _record_request)
    monkeypatch.setattr(agent, "execute_request", _record_execution)
    fact = _user_fact("Let aroute win first", turn_id="turn-aroute-wins")
    fact.payload["user_id"] = "u-aroute-wins"
    fact.payload["session_id"] = "s-aroute-wins"
    fact.delivery_attempt_no = 0
    fact.runtime_command_id = 922

    assert await agent.add_fact(fact)
    await agent.start(event_emitter=None)
    cancel_task: asyncio.Task[dict[str, object] | None] | None = None
    try:
        await asyncio.wait_for(agent.final_check_passed.wait(), timeout=1.0)
        assert agent._session_run_coordinator.get_active_run("s-aroute-wins") is None
        cancel_task = asyncio.create_task(
            agent.request_session_cancel(
                session_id="s-aroute-wins",
                user_id="u-aroute-wins",
                requested_by="user",
                anchor_turn_id="turn-aroute-wins",
            )
        )
        await asyncio.sleep(0)
        assert not cancel_task.done()
        agent.release_run_admission.set()
        await asyncio.wait_for(agent.run_admitted.wait(), timeout=1.0)
        outcome = await asyncio.wait_for(cancel_task, timeout=1.0)
        assert outcome is not None

        for _ in range(100):
            if agent.get_stats()["processed"] == 1:
                break
            await asyncio.sleep(0.01)

        turn = await chat_store.get_turn("turn-aroute-wins")
        delivery = await chat_store.get_user_turn_delivery(
            turn_id="turn-aroute-wins",
        )
        assert turn is not None
        assert turn.status == "cancelled"
        assert delivery is not None
        assert delivery.delivery_state == "terminal"
        assert agent.context_load_calls == 1
        assert forbidden_calls == []
        assert agent.get_stats()["processed"] == 1
        cancelled_run = agent._session_run_coordinator.get_active_run("s-aroute-wins")
        assert cancelled_run is not None
        assert cancelled_run.status == "cancelled"
        assert (
            agent._session_run_coordinator.get_active_run_control(
                "s-aroute-wins",
                cancelled_run.run_id,
            )
            is None
        )
    finally:
        agent.release_run_admission.set()
        agent.cancellation_committed.set()
        if cancel_task is not None and not cancel_task.done():
            cancel_task.cancel()
        await agent.stop()


@pytest.mark.asyncio
async def test_completed_turn_wins_before_pre_admission_cancel(
    runtime_paths_with_schema,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-completed",
        user_id="u-completed",
        turn_id="turn-completed",
        message_text="Already completed",
        created_at_ms=1710000000000,
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id="turn-completed",
        delivery_attempt_no=0,
        command_id=902,
        updated_at_ms=1710000000001,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id="turn-completed",
        delivery_attempt_no=0,
        command_id=902,
        updated_at_ms=1710000000002,
    )
    assert await chat_store.mark_user_turn_delivery_terminal(
        turn_id="turn-completed",
        delivery_attempt_no=0,
        command_id=902,
        updated_at_ms=1710000000003,
    )
    original_turn = await chat_store.get_turn("turn-completed")
    assert original_turn is not None
    await chat_store.upsert_turn(
        replace(
            original_turn,
            status="completed",
            updated_at_ms=1710000000003,
            completed_at_ms=1710000000003,
        )
    )
    agent = ChatTaskAgent(
        agent_id="s-completed",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=chat_store,
    )

    result = await agent.request_session_cancel(
        session_id="s-completed",
        user_id="u-completed",
        requested_by="user",
        anchor_turn_id="turn-completed",
    )

    turn = await chat_store.get_turn("turn-completed")
    delivery = await chat_store.get_user_turn_delivery(turn_id="turn-completed")
    assert result is None
    assert turn is not None
    assert turn.status == "completed"
    assert delivery is not None
    assert delivery.delivery_state == "terminal"


@pytest.mark.asyncio
async def test_message_delete_plan_includes_active_root_that_used_context(
    runtime_paths_with_schema,
) -> None:
    _ = runtime_paths_with_schema
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    run_store = agent._session_run_coordinator._run_store
    run_store.create_active_run(
        "s-chat",
        root_turn_id="turn-root",
        root_user_message="Finish the root task",
        run_id="run-root",
    )
    deleted_fact = _user_fact(
        "Delete an input already consumed by the active run",
        turn_id="turn-delete",
    )
    agent._active_batch_facts = [deleted_fact]

    try:
        terminal_turn_ids = await agent.plan_message_delete_terminal_turn_ids(
            session_id="s-chat",
            turn_id="turn-delete",
        )
    finally:
        agent._active_batch_facts = []

    assert terminal_turn_ids == ("turn-delete", "turn-root")


@pytest.mark.asyncio
async def test_message_delete_plan_replays_pre_run_active_batch(
    runtime_paths_with_schema,
) -> None:
    _ = runtime_paths_with_schema
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    active_fact = _user_fact(
        "Answer after the older message is deleted",
        turn_id="turn-replay",
    )
    queued_fact = _user_fact(
        "Run after the active turn is replayed",
        turn_id="turn-queued",
    )
    agent._active_batch_facts = [active_fact]
    await agent.add_fact(queued_fact)

    try:
        terminal_turn_ids, replay_turn_ids = await agent.plan_message_delete_runtime_turn_ids(
            session_id="s-chat",
            turn_id="turn-delete",
        )
    finally:
        agent._active_batch_facts = []

    assert terminal_turn_ids == ("turn-delete",)
    assert replay_turn_ids == ("turn-replay", "turn-queued")


@pytest.mark.asyncio
async def test_context_replay_abandons_run_without_cancelling_turn(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = runtime_paths_with_schema
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    run_store = agent._session_run_coordinator._run_store
    run_store.create_active_run(
        "s-chat",
        root_turn_id="turn-replay",
        root_user_message="Replay me with clean context",
        run_id="run-replay",
    )
    run_store.register_active_run_control(
        "s-chat",
        "run-replay",
        null_run_control(),
    )
    cancellations: list[dict[str, object]] = []

    async def cancel_run(**scope):  # type: ignore[no-untyped-def]
        cancellations.append(scope)
        return []

    monkeypatch.setattr(session_control_module, "_cancel_child_runs", cancel_run)

    assert await agent.abandon_session_run_for_context_replay(
        session_id="s-chat",
        replay_turn_ids=("turn-replay",),
    )
    assert run_store.get_active_run("s-chat") is None
    assert run_store.get_active_run_control("s-chat", "run-replay") is None
    assert cancellations == [
        {
            "session_id": "s-chat",
            "run_id": "run-replay",
            "run_revision": 0,
            "strict": True,
        }
    ]


@pytest.mark.asyncio
async def test_pending_message_delete_keeps_root_run_and_discards_only_target(
    runtime_paths_with_schema,
) -> None:
    _ = runtime_paths_with_schema
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    run_store = agent._session_run_coordinator._run_store
    run_store.create_active_run(
        "s-chat",
        root_turn_id="turn-root",
        root_user_message="Finish the root task",
        run_id="run-root",
    )
    run_store.append_pending_turn(
        "s-chat",
        "turn-delete",
        "Delete this pending follow-up",
        disposition="message",
    )
    run_store.append_pending_turn(
        "s-chat",
        "turn-keep",
        "Keep this later follow-up",
        disposition="message",
    )
    deleted_fact = _user_fact(
        "Delete this pending follow-up",
        turn_id="turn-delete",
    )
    agent._fact_memory = [
        _user_fact("Finish the root task", turn_id="turn-root"),
        deleted_fact,
    ]
    agent._last_batch_facts = [deleted_fact]
    assert await agent.add_fact(deleted_fact)

    assert await agent.plan_message_delete_terminal_turn_ids(
        session_id="s-chat",
        turn_id="turn-delete",
    ) == ("turn-delete",)
    discarded = await agent.discard_pending_turn_for_message_delete(
        session_id="s-chat",
        turn_id="turn-delete",
        run_id="run-root",
        run_revision=0,
    )

    active_run = run_store.get_active_run("s-chat")
    assert discarded is True
    assert active_run is not None
    assert active_run.run_id == "run-root"
    assert active_run.revision == 0
    assert active_run.root_turn_id == "turn-root"
    assert [turn.turn_id for turn in active_run.pending_turns] == ["turn-keep"]
    assert agent._fact_queue.empty()
    assert [
        fact.payload["turn_id"]
        for fact in agent._fact_memory
        if fact.event_type == EventTypes.USER_MESSAGE
    ] == ["turn-root"]
    assert agent._last_batch_facts == []


@pytest.mark.asyncio
async def test_pending_delete_linearizes_before_checkpoint_consumption() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    run_store = agent._session_run_coordinator._run_store
    run_store.create_active_run(
        "s-chat",
        root_turn_id="turn-root",
        root_user_message="Finish the root task",
        run_id="run-root",
    )
    run_store.append_pending_turn(
        "s-chat",
        "turn-delete",
        "Do not include this deleted follow-up",
        disposition="message",
    )
    checkpoint_fact = _tool_loop_fact()
    merged = await agent.merge_facts([checkpoint_fact])

    await agent._fact_transfer_lock.acquire()
    delete_task = asyncio.create_task(
        agent.discard_pending_turn_for_message_delete(
            session_id="s-chat",
            turn_id="turn-delete",
            run_id="run-root",
            run_revision=0,
        )
    )
    build_task: asyncio.Task | None = None
    try:
        for _ in range(100):
            if agent._execution_admission_lock.locked():
                break
            await asyncio.sleep(0.01)
        assert agent._execution_admission_lock.locked()

        build_task = asyncio.create_task(agent.build_context(merged))
        await asyncio.sleep(0)
        assert not build_task.done()

        agent._fact_transfer_lock.release()
        assert await asyncio.wait_for(delete_task, timeout=1.0)
        context = await asyncio.wait_for(build_task, timeout=1.0)

        active_run = run_store.get_active_run("s-chat")
        assert active_run is not None
        assert active_run.pending_turns == []
        assert context.planner_fact_kind == IncomingFactKind.OTHER_FACT
        assert "deleted follow-up" not in context.latest_user_message
    finally:
        if agent._fact_transfer_lock.locked():
            agent._fact_transfer_lock.release()
        if not delete_task.done():
            delete_task.cancel()
        if build_task is not None and not build_task.done():
            build_task.cancel()


@pytest.mark.asyncio
async def test_queued_message_delete_does_not_interrupt_active_root() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    run_store = agent._session_run_coordinator._run_store
    run_store.create_active_run(
        "s-chat",
        root_turn_id="turn-root",
        root_user_message="Finish the root task",
        run_id="run-root",
    )
    run_store.bump_revision("s-chat")
    root_fact = _user_fact("Finish the root task", turn_id="turn-root")
    deleted_fact = _user_fact("Delete this queued follow-up", turn_id="turn-delete")
    agent._active_batch_facts = [root_fact]
    agent._fact_memory = [root_fact]
    assert await agent.add_fact(deleted_fact)

    try:
        assert await agent.plan_message_delete_terminal_turn_ids(
            session_id="s-chat",
            turn_id="turn-delete",
        ) == ("turn-delete",)
        discarded = await agent.discard_pending_turn_for_message_delete(
            session_id="s-chat",
            turn_id="turn-delete",
            run_id=None,
            run_revision=1,
        )
    finally:
        agent._active_batch_facts = []

    active_run = run_store.get_active_run("s-chat")
    assert discarded is True
    assert active_run is not None
    assert active_run.run_id == "run-root"
    assert active_run.revision == 1
    assert active_run.root_turn_id == "turn-root"
    assert agent._fact_queue.empty()
    assert agent._fact_memory == [root_fact]


@pytest.mark.asyncio
async def test_release_pending_inputs_requeues_original_durable_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unconsumed-input handoff preserves the original turn and full runtime envelope."""

    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await store.initialize()
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime.db"))
    await queue.start()
    monkeypatch.setattr(
        "magi.core.runtime_bindings.require_runtime_command_queue",
        lambda: queue,
    )
    pending_turn_id = "turn-pending-original"
    content = "And also draft the release notes after."
    attachments = [{"attachment_id": "att-1", "kind": "document"}]
    metadata = {"reply_to_message_id": "msg-root", "custom": "keep-me"}
    await store.create_user_turn_once(
        session_id="s-chat",
        user_id="u-chat",
        turn_id=pending_turn_id,
        message_text=content,
        created_at_ms=1710000000000,
        runtime_envelope={
            "source": "api",
            "user_id": "u-chat",
            "session_id": "s-chat",
            "turn_id": pending_turn_id,
            "message": content,
            "attachments": attachments,
            "workspace_path": "/tmp/project",
            "interaction_kind": None,
            "metadata": metadata,
            "runtime_namespace": "desktop",
        },
        request_fingerprint="pending-input-fingerprint",
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id=pending_turn_id,
        delivery_attempt_no=0,
        command_id=10,
        updated_at_ms=1710000000001,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id=pending_turn_id,
        delivery_attempt_no=0,
        command_id=10,
        updated_at_ms=1710000000002,
    )

    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Plan the refactor.",
            turn_id="turn-root",
            source="api",
        )  # type: ignore[arg-type]
    )
    agent._session_run_coordinator._run_store.append_pending_turn(
        "s-chat",
        pending_turn_id,
        content,
        disposition="message",
    )

    try:
        active_run = agent._session_run_coordinator.get_active_run("s-chat")
        assert active_run is not None
        completed, pending_inputs = agent._session_run_coordinator.complete_run_with_pending_inputs(
            session_id="s-chat",
            run_id=active_run.run_id,
            revision=active_run.revision,
        )
        assert completed
        await agent._release_pending_inputs("s-chat", pending_inputs)

        delivery = await store.get_user_turn_delivery(turn_id=pending_turn_id)
        assert delivery is not None
        assert delivery.delivery_attempt_no == 1
        assert delivery.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert agent._session_run_coordinator.get_active_run("s-chat") is None

        command = await queue.claim_next(
            consumer_name="test",
            command_types=[RuntimeCommandType.USER_MESSAGE],
        )
        assert command is not None
        assert command.payload["turn_id"] == pending_turn_id
        assert command.payload["attachments"] == attachments
        assert command.payload["workspace_path"] == "/tmp/project"
        assert command.payload["metadata"] == metadata
        assert command.delivery_attempt_no == 1
    finally:
        await queue.stop()
        await store.shutdown()
