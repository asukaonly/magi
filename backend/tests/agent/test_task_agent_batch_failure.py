from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import TaskAgent
from magi.agent.runtime.types import TaskAgentType
from magi.agent.task_agents.common import (
    ExecutionResult,
    IncomingFactKind,
    UserMessagePayload,
)
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
from magi.chat import ChatMessageRecord, ChatStore
from magi.chat.contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_TERMINAL,
)
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.chat.task_agent import chat_task_agent as chat_task_agent_module
from magi.events.events import EventTypes


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


class _FakeEventEmitter:
    async def emit_chat_response_event(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None


def _fact(
    *,
    session_id: str,
    turn_id: str,
    delivery_attempt_no: int = 0,
    runtime_command_id: int = 101,
) -> FactRecord:
    return FactRecord(
        agent_id=f"chat:{session_id}",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id=session_id,
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "user-1",
            "session_id": session_id,
            "turn_id": turn_id,
            "content": f"message for {turn_id}",
        },
        correlation_id=f"user_message:{turn_id}",
        delivery_attempt_no=delivery_attempt_no,
        runtime_command_id=runtime_command_id,
    )


async def _create_admitted_turn(
    store: ChatStore,
    *,
    session_id: str,
    turn_id: str,
    delivery_attempt_no: int = 0,
    runtime_command_id: int = 101,
    run_id: str | None = None,
) -> None:
    await store.create_user_turn(
        session_id=session_id,
        user_id="user-1",
        turn_id=turn_id,
        message_text=f"message for {turn_id}",
        created_at_ms=100,
        run_id=run_id,
        runtime_envelope={
            "source": "api",
            "user_id": "user-1",
            "session_id": session_id,
            "turn_id": turn_id,
            "message": f"message for {turn_id}",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint=f"request:{turn_id}",
    )
    current_attempt = 0
    while current_attempt < delivery_attempt_no:
        prepared = await store.prepare_user_turn_delivery_attempt(
            turn_id=turn_id,
            expected_attempt_no=current_attempt,
            updated_at_ms=110 + current_attempt,
        )
        assert prepared is not None
        current_attempt = prepared.delivery_attempt_no
    assert await store.mark_user_turn_delivery_queued(
        turn_id=turn_id,
        delivery_attempt_no=delivery_attempt_no,
        command_id=runtime_command_id,
        updated_at_ms=120,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id=turn_id,
        delivery_attempt_no=delivery_attempt_no,
        command_id=runtime_command_id,
        updated_at_ms=130,
    )


async def _wait_for_terminal(store: ChatStore, *, turn_id: str) -> None:
    for _ in range(100):
        delivery = await store.get_user_turn_delivery(turn_id=turn_id)
        if delivery is not None and delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Turn {turn_id!r} did not become terminal")


async def _wait_for_active_run_completion(
    agent: ChatTaskAgent,
    *,
    session_id: str,
) -> None:
    for _ in range(100):
        if agent._session_run_coordinator.get_active_run(session_id) is None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Session {session_id!r} still has an active run")


class _FailingPipelineChatAgent(ChatTaskAgent):
    def __init__(self, *, fail_stage: str, chat_store: ChatStore) -> None:
        super().__init__(
            agent_id="session-failure",
            llm_adapter=_FakeLLMAdapter(),
            chat_store=chat_store,
        )
        self._fail_stage = fail_stage
        if fail_stage == "postprocess":

            async def _fail_postprocess(*_args, **_kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("postprocess service failed")

            self._postprocess_service.handle = _fail_postprocess

    async def build_context(self, merged_facts):  # type: ignore[no-untyped-def]
        if self._fail_stage == "build_context":
            raise RuntimeError("build context failed")
        return SimpleNamespace(
            merged_facts=merged_facts,
            session_id="session-failure",
            session_run_id=None,
        )

    async def admit_context(self, context):  # type: ignore[no-untyped-def]
        if self._fail_stage == "admit_context":
            raise RuntimeError("context admission failed")
        return object()

    async def resolve_capabilities(self, context, admission):  # type: ignore[no-untyped-def]
        return object()

    async def build_execution_request(  # type: ignore[no-untyped-def]
        self,
        context,
        admission,
        capabilities,
    ):
        return object()

    async def execute_request(self, context, request):  # type: ignore[no-untyped-def]
        return object()

    async def finalize_result(self, context, result) -> None:  # type: ignore[no-untyped-def]
        if self._fail_stage == "finalize_result":
            raise RuntimeError("postprocess failed")
        if self._fail_stage == "postprocess":
            await super().finalize_result(context, result)


class _EmptyVisibleResponseChatAgent(ChatTaskAgent):
    async def build_context(self, merged_facts):  # type: ignore[no-untyped-def]
        source_fact = next(
            fact
            for fact in reversed(self._last_batch_facts)
            if fact.event_type == EventTypes.USER_MESSAGE
        )
        payload = source_fact.payload
        session_id = str(payload["session_id"])
        turn_id = str(payload["turn_id"])
        active_run = self._session_run_coordinator.get_active_run(session_id)
        assert active_run is not None
        return ChatRuntimeContext(
            latest_fact=source_fact,
            recent_facts=list(merged_facts),
            batch_facts=list(self._last_batch_facts),
            agent_id=self.agent_id,
            agent_type=TaskAgentType.CHAT.value,
            runtime_key=self.runtime_key,
            user_id=str(payload["user_id"]),
            session_id=session_id,
            history_key=f"user-1::{session_id}",
            history=[],
            conversation_history=[],
            latest_user_message=str(payload["content"]),
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=UserMessagePayload(
                user_id=str(payload["user_id"]),
                session_id=session_id,
                content=str(payload["content"]),
                turn_id=turn_id,
            ),
            active_run=active_run,
            session_run_id=active_run.run_id,
            session_run_revision=active_run.revision,
            session_run_disposition="start",
        )

    async def admit_context(self, context):  # type: ignore[no-untyped-def]
        return object()

    async def resolve_capabilities(self, context, admission):  # type: ignore[no-untyped-def]
        return object()

    async def build_execution_request(  # type: ignore[no-untyped-def]
        self,
        context,
        admission,
        capabilities,
    ):
        return object()

    async def execute_request(self, context, request):  # type: ignore[no-untyped-def]
        turn_id = str(context.latest_payload.turn_id)
        return ExecutionResult(
            mode=None,
            response_text="",
            turn_id=turn_id,
            ux_plan={"assistant_surface_mode": "final_only"},
        )


class _SuccessfulVisibleResponseChatAgent(ChatTaskAgent):
    async def admit_context(self, context):  # type: ignore[no-untyped-def]
        return object()

    async def resolve_capabilities(self, context, admission):  # type: ignore[no-untyped-def]
        return object()

    async def build_execution_request(  # type: ignore[no-untyped-def]
        self,
        context,
        admission,
        capabilities,
    ):
        return object()

    async def execute_request(self, context, request):  # type: ignore[no-untyped-def]
        turn_id = str(context.latest_payload.turn_id)
        return ExecutionResult(
            mode=None,
            response_text=f"reply to {turn_id}",
            turn_id=turn_id,
            ux_plan={"assistant_surface_mode": "final_only"},
        )


@pytest.mark.asyncio
async def test_two_admitted_user_turns_with_source_both_reach_terminal(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    session_id = "session-two-admitted"
    first_turn_id = "turn-admitted-first"
    second_turn_id = "turn-admitted-second"
    await _create_admitted_turn(
        store,
        session_id=session_id,
        turn_id=first_turn_id,
        runtime_command_id=101,
    )
    await _create_admitted_turn(
        store,
        session_id=session_id,
        turn_id=second_turn_id,
        runtime_command_id=102,
    )
    first_fact = _fact(
        session_id=session_id,
        turn_id=first_turn_id,
        runtime_command_id=101,
    )
    source_fact = FactRecord(
        agent_id=f"chat:{session_id}",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id=session_id,
        event_type="SOURCE_CONTEXT_UPDATED",
        payload={"session_id": session_id, "content": "context between turns"},
    )
    second_fact = _fact(
        session_id=session_id,
        turn_id=second_turn_id,
        runtime_command_id=102,
    )
    agent = _SuccessfulVisibleResponseChatAgent(
        agent_id=session_id,
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    for fact in (first_fact, source_fact, second_fact):
        assert await agent.add_fact(fact)

    await agent.start(event_emitter=_FakeEventEmitter())
    try:
        await _wait_for_terminal(store, turn_id=first_turn_id)
        await _wait_for_terminal(store, turn_id=second_turn_id)
        for _ in range(100):
            if agent.get_stats()["processed"] == 3:
                break
            await asyncio.sleep(0.01)
    finally:
        await agent.stop()

    for turn_id in (first_turn_id, second_turn_id):
        delivery = await store.get_user_turn_delivery(turn_id=turn_id)
        final = await store.get_latest_message_for_turn(
            turn_id,
            message_kind="assistant_final",
        )
        assert delivery is not None
        assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
        assert final is not None
        assert final.content_text == f"reply to {turn_id}"
    assert agent.get_stats()["processed"] == 3


@pytest.mark.asyncio
async def test_empty_visible_response_uses_retryable_failure_finalizer_once(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    session_id = "session-empty-visible"
    turn_id = "turn-empty-visible"
    await _create_admitted_turn(
        store,
        session_id=session_id,
        turn_id=turn_id,
    )
    fact = _fact(session_id=session_id, turn_id=turn_id)
    agent = _EmptyVisibleResponseChatAgent(
        agent_id=session_id,
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        session_id,
        root_turn_id=turn_id,
        root_user_message=f"message for {turn_id}",
        run_id="run-empty-visible",
    )

    await agent.start(event_emitter=_FakeEventEmitter())
    try:
        assert await agent.add_fact(fact)
        await _wait_for_terminal(store, turn_id=turn_id)
    finally:
        await agent.stop()

    assert agent.get_stats()["failed"] == 1
    assert agent._session_run_coordinator.get_active_run(session_id) is None

    restarted_agent = ChatTaskAgent(
        agent_id=session_id,
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    await restarted_agent.handle_batch_failure(
        [fact],
        error=RuntimeError("duplicate restart finalization"),
        stage="finalize_result",
        context=None,
    )

    delivery = await store.get_user_turn_delivery(turn_id=turn_id)
    messages = [
        message
        for message in await store.list_messages(session_id=session_id)
        if message.turn_id == turn_id
        and message.message_kind == "assistant_final"
        and message.is_visible
    ]
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert len(messages) == 1
    assert json.loads(messages[0].payload_json)["delivery_failure"]["retryable"] is True


@pytest.mark.parametrize(
    ("fail_stage", "recorded_stage"),
    [
        ("build_context", "build_context"),
        ("admit_context", "admit_context"),
        ("finalize_result", "finalize_result"),
        ("postprocess", "finalize_result"),
    ],
)
@pytest.mark.asyncio
async def test_chat_pipeline_failure_writes_retryable_terminal_surface(
    runtime_paths_with_schema,
    fail_stage: str,
    recorded_stage: str,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    turn_id = f"turn-failure-{fail_stage}"
    run_id = f"run-{fail_stage}"
    await _create_admitted_turn(
        store,
        session_id="session-failure",
        turn_id=turn_id,
        run_id=run_id,
    )
    agent = _FailingPipelineChatAgent(
        fail_stage=fail_stage,
        chat_store=store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        "session-failure",
        root_turn_id=turn_id,
        root_user_message=f"message for {turn_id}",
        run_id=run_id,
    )
    fact = _fact(session_id="session-failure", turn_id=turn_id)

    await agent.start(event_emitter=None)
    try:
        assert await agent.add_fact(fact)
        await _wait_for_terminal(store, turn_id=turn_id)
        await _wait_for_active_run_completion(
            agent,
            session_id="session-failure",
        )
    finally:
        await agent.stop()

    delivery = await store.get_user_turn_delivery(turn_id=turn_id)
    turn = await store.get_turn(turn_id)
    final = await store.get_latest_message_for_turn(
        turn_id,
        message_kind="assistant_final",
    )
    assert delivery is not None
    assert delivery.delivery_attempt_no == 0
    assert delivery.current_command_id == 101
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert turn is not None
    assert turn.status == "failed"
    assert turn.completed_at_ms is not None
    assert final is not None
    assert final.is_visible is True
    assert agent._session_run_coordinator.get_active_run("session-failure") is None
    payload = json.loads(final.payload_json)
    assert payload["delivery_failure"] == {
        "status": "failed",
        "retryable": True,
        "stage": recorded_stage,
        "delivery_attempt_no": 0,
        "runtime_command_id": 101,
    }
    model_context = await store.load_model_context(session_id="session-failure")
    accepted_outcomes = [
        item
        for item in model_context.items
        if bool(item.metadata.get("accepted_outcome"))
        and item.metadata.get("origin_turn_id") == turn_id
    ]
    assert len(accepted_outcomes) == 1
    assert accepted_outcomes[0].message["role"] == "user"
    assert str(accepted_outcomes[0].message["content"]).startswith(
        "[Runtime outcome] The turn ended with status 'failed'"
    )
    assert final.content_text not in {
        str(item.message.get("content") or "") for item in model_context.items
    }
    assert agent.get_stats()["failed"] == 1


@pytest.mark.asyncio
async def test_budget_failure_writes_execution_limit_terminal_surface(
    runtime_paths_with_schema,
) -> None:
    from magi.agent.execution.task_budget import TaskBudgetExceeded
    from magi.i18n import language_context

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    turn_id = "turn-budget-failure"
    await _create_admitted_turn(
        store,
        session_id="session-budget-failure",
        turn_id=turn_id,
    )
    agent = ChatTaskAgent(
        agent_id="session-budget-failure",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )

    with language_context("en"):
        finalized = await agent._postprocess_service.handle_pipeline_failure(
            source_fact=_fact(
                session_id="session-budget-failure",
                turn_id=turn_id,
            ),
            error=TaskBudgetExceeded(
                resource="llm_calls",
                limit=30,
                used=30,
                requested=1,
            ),
            stage="admit_context",
        )

    final = await store.get_latest_message_for_turn(
        turn_id,
        message_kind="assistant_final",
    )
    assert finalized is True
    assert final is not None
    assert "execution limit" in str(final.content_text)
    assert "Send it again" not in str(final.content_text)
    turn = await store.get_turn(turn_id)
    assert turn is not None
    assert turn.status == "failed"


@pytest.mark.asyncio
async def test_pipeline_failure_uses_shared_pending_input_release_barrier(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    session_id = "session-failure-barrier"
    turn_id = "turn-failure-barrier"
    await _create_admitted_turn(
        store,
        session_id=session_id,
        turn_id=turn_id,
    )
    agent = ChatTaskAgent(
        agent_id=session_id,
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        session_id,
        root_turn_id=turn_id,
        root_user_message=f"message for {turn_id}",
        run_id="run-failure-barrier",
    )
    agent._session_run_coordinator._run_store.append_pending_turn(
        session_id,
        "turn-input",
        "Handle this after the failed root task",
        disposition="message",
    )
    barrier_calls: list[tuple[str, str, int, list[str]]] = []

    async def _release_pending(
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

    monkeypatch.setattr(
        agent._postprocess_service,
        "release_pending_inputs_after_run_completion",
        _release_pending,
    )

    await agent.handle_batch_failure(
        [_fact(session_id=session_id, turn_id=turn_id)],
        error=RuntimeError("pipeline failed"),
        stage="finalize_result",
        context=None,
    )

    assert barrier_calls == [(session_id, "run-failure-barrier", 0, ["turn-input"])]


@pytest.mark.asyncio
async def test_pipeline_failure_finalization_retries_without_rerunning_pipeline(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    session_id = "session-failure-retry"
    turn_id = "turn-failure-retry"
    await _create_admitted_turn(
        store,
        session_id=session_id,
        turn_id=turn_id,
    )
    agent = ChatTaskAgent(
        agent_id=session_id,
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        session_id,
        root_turn_id=turn_id,
        root_user_message=f"message for {turn_id}",
        run_id="run-failure-retry",
    )
    original = agent._postprocess_service.handle_pipeline_failure
    finalization_attempts = 0
    finalization_allowed = asyncio.Event()

    async def _wait_then_finalize(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal finalization_attempts
        finalization_attempts += 1
        if not finalization_allowed.is_set():
            raise OSError("chat database temporarily unavailable")
        return await original(**kwargs)

    monkeypatch.setattr(
        agent._postprocess_service,
        "handle_pipeline_failure",
        _wait_then_finalize,
    )
    monkeypatch.setattr(
        chat_task_agent_module,
        "_PIPELINE_FAILURE_RETRY_INITIAL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        chat_task_agent_module,
        "_PIPELINE_FAILURE_RETRY_MAX_SECONDS",
        0.005,
    )
    fact = _fact(session_id=session_id, turn_id=turn_id)
    agent._active_batch_facts = [fact]

    try:
        finalization = asyncio.create_task(
            agent.handle_batch_failure(
                [fact],
                error=RuntimeError("pipeline failed"),
                stage="finalize_result",
                context=None,
            )
        )
        for _ in range(100):
            if finalization_attempts > 0:
                break
            await asyncio.sleep(0.001)
        assert finalization.done() is False
        assert agent.has_inflight_work() is True
        finalization_allowed.set()
        await asyncio.wait_for(finalization, timeout=1)
        await _wait_for_terminal(store, turn_id=turn_id)
    finally:
        agent._active_batch_facts = []
        await agent.stop()

    assert finalization_attempts >= 2
    assert agent._session_run_coordinator.get_active_run(session_id) is None
    assert agent.has_inflight_work() is False


@pytest.mark.asyncio
async def test_old_failed_attempt_cannot_write_surface_or_close_new_attempt(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    turn_id = "turn-stale-failure"
    await _create_admitted_turn(
        store,
        session_id="session-failure",
        turn_id=turn_id,
        delivery_attempt_no=0,
        runtime_command_id=101,
    )
    prepared = await store.prepare_user_turn_delivery_attempt(
        turn_id=turn_id,
        expected_attempt_no=0,
        updated_at_ms=200,
    )
    assert prepared is not None
    assert prepared.delivery_attempt_no == 1
    assert await store.mark_user_turn_delivery_queued(
        turn_id=turn_id,
        delivery_attempt_no=1,
        command_id=202,
        updated_at_ms=210,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id=turn_id,
        delivery_attempt_no=1,
        command_id=202,
        updated_at_ms=220,
    )
    agent = ChatTaskAgent(
        agent_id="session-failure",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        "session-failure",
        root_turn_id=turn_id,
        root_user_message=f"message for {turn_id}",
        run_id="run-new-attempt",
    )

    await agent.handle_batch_failure(
        [_fact(session_id="session-failure", turn_id=turn_id)],
        error=RuntimeError("old attempt failed"),
        stage="finalize_result",
        context=None,
    )

    delivery = await store.get_user_turn_delivery(turn_id=turn_id)
    final = await store.get_latest_message_for_turn(
        turn_id,
        message_kind="assistant_final",
    )
    turn = await store.get_turn(turn_id)
    assert delivery is not None
    assert delivery.delivery_attempt_no == 1
    assert delivery.current_command_id == 202
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_ADMITTED
    assert final is None
    assert turn is not None
    assert turn.status == "queued"
    active_run = agent._session_run_coordinator.get_active_run("session-failure")
    assert active_run is not None
    assert active_run.run_id == "run-new-attempt"


@pytest.mark.asyncio
async def test_pipeline_failure_preserves_already_persisted_final_response(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    turn_id = "turn-persisted-final"
    await _create_admitted_turn(
        store,
        session_id="session-failure",
        turn_id=turn_id,
        run_id="run-persisted-final",
    )
    turn = await store.get_turn(turn_id)
    assert turn is not None
    turn.response_mode = "interim_then_final"
    await store.upsert_turn(turn)
    await store.append_message(
        ChatMessageRecord(
            message_id="msg-existing-final",
            session_id="session-failure",
            turn_id=turn_id,
            user_id="user-1",
            role="assistant",
            message_kind="assistant_final",
            content_text="The answer was already saved.",
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=200,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    agent = ChatTaskAgent(
        agent_id="session-failure",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        "session-failure",
        root_turn_id=turn_id,
        root_user_message=f"message for {turn_id}",
        run_id="run-persisted-final",
    )

    await agent.handle_batch_failure(
        [_fact(session_id="session-failure", turn_id=turn_id)],
        error=RuntimeError("notification failed"),
        stage="finalize_result",
        context=None,
    )

    delivery = await store.get_user_turn_delivery(turn_id=turn_id)
    completed_turn = await store.get_turn(turn_id)
    messages = await store.list_messages(session_id="session-failure")
    visible_finals = [
        message
        for message in messages
        if message.turn_id == turn_id
        and message.message_kind == "assistant_final"
        and message.is_visible
    ]
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert completed_turn is not None
    assert completed_turn.status == "completed"
    assert completed_turn.response_mode == "interim_then_final"
    assert [message.message_id for message in visible_finals] == ["msg-existing-final"]
    assert visible_finals[0].content_text == "The answer was already saved."
    assert "delivery_failure" not in json.loads(visible_finals[0].payload_json)
    model_context = await store.load_model_context(session_id="session-failure")
    accepted_outcomes = [
        item
        for item in model_context.items
        if bool(item.metadata.get("accepted_outcome"))
        and item.metadata.get("origin_turn_id") == turn_id
    ]
    assert len(accepted_outcomes) == 1
    assert accepted_outcomes[0].message == {
        "role": "assistant",
        "content": "The answer was already saved.",
    }
    assert agent._session_run_coordinator.get_active_run("session-failure") is None


@pytest.mark.parametrize("status", ["failed", "blocked"])
@pytest.mark.asyncio
async def test_reconcile_finished_active_run_clears_unsuccessful_terminal_turn(
    runtime_paths_with_schema,
    status: str,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    session_id = f"session-reconcile-{status}"
    turn_id = f"turn-reconcile-{status}"
    await _create_admitted_turn(
        store,
        session_id=session_id,
        turn_id=turn_id,
    )
    turn = await store.get_turn(turn_id)
    assert turn is not None
    turn.status = status
    await store.upsert_turn(turn)
    agent = ChatTaskAgent(
        agent_id=session_id,
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )
    agent._session_run_coordinator._run_store.create_active_run(
        session_id,
        root_turn_id=turn_id,
        root_user_message=f"message for {turn_id}",
        run_id=f"run-reconcile-{status}",
    )

    await agent._reconcile_finished_active_run(session_id)

    assert agent._session_run_coordinator.get_active_run(session_id) is None


@pytest.mark.asyncio
async def test_pipeline_failure_hides_incomplete_rhythm_before_retry_surface(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    turn_id = "turn-partial-rhythm"
    await _create_admitted_turn(
        store,
        session_id="session-failure",
        turn_id=turn_id,
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="msg-partial-rhythm",
            session_id="session-failure",
            turn_id=turn_id,
            user_id="user-1",
            role="assistant",
            message_kind="assistant_rhythm_segment",
            content_text="Only the first part",
            payload_json=json.dumps({"rhythm": {"segment_count": 2, "segment_index": 0}}),
            is_final=True,
            is_visible=True,
            created_at_ms=200,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    agent = ChatTaskAgent(
        agent_id="session-failure",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=store,
    )

    await agent.handle_batch_failure(
        [_fact(session_id="session-failure", turn_id=turn_id)],
        error=RuntimeError("postprocess failed"),
        stage="finalize_result",
        context=None,
    )

    messages = await store.list_messages(session_id="session-failure")
    partial = next(message for message in messages if message.message_id == "msg-partial-rhythm")
    visible_final = next(
        message
        for message in messages
        if message.turn_id == turn_id
        and message.message_kind == "assistant_final"
        and message.is_visible
    )
    assert partial.is_visible is False
    assert json.loads(visible_final.payload_json)["delivery_failure"]["retryable"] is True


@pytest.mark.asyncio
async def test_generic_task_agent_does_not_replay_failed_batch() -> None:
    processed: list[str] = []
    failure_calls: list[tuple[str, str]] = []

    class _GenericAgent(TaskAgent):
        def __init__(self) -> None:
            super().__init__(TaskAgentType.TIMELINE, "generic-failure")
            self._batch_size = 1
            self._failed_once = False

        async def build_context(self, merged_facts):  # type: ignore[no-untyped-def]
            content = str(merged_facts[-1].payload["content"])
            if content == "fail" and not self._failed_once:
                self._failed_once = True
                raise RuntimeError("generic failure")
            return content

        async def finalize_result(self, context, result) -> None:  # type: ignore[no-untyped-def]
            processed.append(str(context))

        async def handle_batch_failure(  # type: ignore[no-untyped-def]
            self,
            batch,
            *,
            error,
            stage,
            context,
        ) -> None:
            failure_calls.append((str(batch[0].payload["content"]), stage))

    agent = _GenericAgent()
    failed_fact = FactRecord(
        agent_id="timeline:generic-failure",
        agent_type=TaskAgentType.TIMELINE.value,
        agent_instance_id="generic-failure",
        event_type="test",
        payload={"content": "fail"},
    )
    succeeding_fact = FactRecord(
        agent_id="timeline:generic-failure",
        agent_type=TaskAgentType.TIMELINE.value,
        agent_instance_id="generic-failure",
        event_type="test",
        payload={"content": "succeed"},
    )

    await agent.start(event_emitter=None)
    try:
        assert await agent.add_fact(failed_fact)
        assert await agent.add_fact(succeeding_fact)
        for _ in range(100):
            if agent.get_stats()["processed"] == 2:
                break
            await asyncio.sleep(0.01)
    finally:
        await agent.stop()

    assert failure_calls == [("fail", "build_context")]
    assert processed == ["succeed"]
    assert agent.get_stats()["failed"] == 1


@pytest.mark.asyncio
async def test_filtered_batch_is_counted_exactly_once() -> None:
    parsed: list[object] = []

    class _FilteringAgent(TaskAgent):
        async def merge_facts(self, new_facts):  # type: ignore[no-untyped-def]
            return []

        async def finalize_result(self, context, result) -> None:  # type: ignore[no-untyped-def]
            parsed.append(result)

    agent = _FilteringAgent(TaskAgentType.TIMELINE, "filtered-batch")
    agent._batch_size = 2
    facts = [
        FactRecord(
            agent_id="timeline:filtered-batch",
            agent_type=TaskAgentType.TIMELINE.value,
            agent_instance_id="filtered-batch",
            event_type="test",
            payload={"index": index},
        )
        for index in range(2)
    ]

    await agent.start(event_emitter=None)
    try:
        for fact in facts:
            assert await agent.add_fact(fact)
        for _ in range(100):
            if agent.get_stats()["processed"] == 2:
                break
            await asyncio.sleep(0.01)
    finally:
        await agent.stop()

    assert agent.get_stats()["processed"] == 2
    assert agent.get_stats()["failed"] == 0
    assert parsed == []
