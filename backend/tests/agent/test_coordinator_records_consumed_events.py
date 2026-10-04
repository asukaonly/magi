"""ChatExecutionCoordinator records which messages each
run consumed into ConversationLog.

When the coordinator drives a unified agent run, it must
emit a ``record_consumed(session_id, run_id, revision, message_ids)``
call before the runner starts, so that a later cross-run retract can
find this run via ``ConversationLog.find_dependents``.

The list of message_ids comes from the wired log itself
(``log.list_visible_message_ids``), so the coordinator is decoupled from
the in-memory history representation (which only carries role/content).
"""

from __future__ import annotations

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.handlers import (
    ChatRuntimeContext,
    ExecutionHandlerRegistry,
    UserMessagePayload,
)
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.handlers.contracts import TurnAdmissionDecision
from magi.chat.task_agent.fact_classifier import (
    ChatFactClassifier,
    IncomingFactKind,
)
from magi.agent.task_agents.common.contracts import (
    ExecutionRequest,
    ExecutionResult,
    CapabilitySelection,
)
from magi.events.events import EventTypes


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _FakeToolRegistry:
    def list_tools(self, **kwargs) -> list[str]:  # type: ignore[no-untyped-def]
        _ = kwargs
        return []

    def get_skill_names(self) -> list[str]:
        return []


class _FakeAgentRunHandler:
    def __init__(self, response_text: str = "ok") -> None:
        self._result = ExecutionResult(
            mode=None,
            response_text=response_text,
        )
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return self._result


def _build_context(
    *,
    user_id: str = "u1",
    session_id: str = "s1",
    run_id: str = "run-1",
    revision: int = 0,
) -> ChatRuntimeContext:
    fact = FactRecord(
        agent_id=f"chat:{user_id}",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": user_id, "session_id": session_id, "content": "hi"},
    )
    ctx = ChatRuntimeContext(
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
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(
            dict(fact.payload),
            fallback_user_id=user_id,
        ),
        session_run_id=run_id,
        session_run_revision=revision,
    )
    return ctx


def _build_request(ctx: ChatRuntimeContext) -> ExecutionRequest:
    admission = TurnAdmissionDecision(
        run_kind="chat",
        execution_mode=None,
        reasoning="",
    )
    return ExecutionRequest(
        mode=None,
        context=ctx,
        admission=admission,
        capabilities=CapabilitySelection(tools=[], reasoning="", task_hint={}),
    )


def _build_coordinator(*, conversation_log, handler=None) -> ChatExecutionCoordinator:
    return ChatExecutionCoordinator(
        tool_registry=_FakeToolRegistry(),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        agent_run_handler=handler if handler is not None else _FakeAgentRunHandler(),
        conversation_log=conversation_log,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visible_context_dependencies_are_durable_before_handler_execution(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from magi.chat.conversation_log import ChatRunConsumedEventsStore, ConversationLog
    from magi.chat.store import ChatStore
    from magi_plugin_sdk.conversation import ContentBlock, ConversationEvent

    db_path = str(tmp_path / "chat.db")
    messages = ChatStore(db_path=db_path)
    await messages.initialize()
    consumed = ChatRunConsumedEventsStore(db_path=db_path)
    await consumed.initialize()
    log = ConversationLog(messages_repo=messages, consumed_events_store=consumed)
    try:
        for event_id, text, session_id in [
            ("m1", "Book a train", "s1"),
            ("m2", "Depart tomorrow", "s1"),
            ("hidden", "Discard this", "s1"),
            ("other", "Another conversation", "s2"),
        ]:
            await log.append(
                ConversationEvent(
                    event_id=event_id,
                    event_type="user_message",
                    timestamp_ms=1000,
                    actor="u1",
                    content=[ContentBlock(kind="text", text=text)],
                ),
                session_id=session_id,
            )
        await log.append(
            ConversationEvent(
                event_id="redaction",
                event_type="message_redacted",
                timestamp_ms=2000,
                actor="u1",
                content=None,
                redacts="hidden",
            ),
            session_id="s1",
        )
        ctx = _build_context(session_id="s1", run_id="run-1", revision=2)
        ctx.conversation_history = [
            {"role": "user", "content": block.text}
            for block in await log.materialize(session_id="s1")
        ]
        request = _build_request(ctx)

        async def execute(received):
            assert received is request
            assert received.context.conversation_history == [
                {"role": "user", "content": "Book a train"},
                {"role": "user", "content": "Depart tomorrow"},
            ]
            # Check persisted dependencies before the handler can produce output.
            for message_id in ("m1", "m2"):
                assert await log.find_dependents(session_id="s1", message_id=message_id) == [
                    ("run-1", 2)
                ]
            for message_id in ("hidden", "redaction", "other"):
                assert await log.find_dependents(session_id="s1", message_id=message_id) == []
            assert await log.find_dependents(session_id="s2", message_id="other") == []
            return ExecutionResult(mode=None, response_text="Train options ready")

        handler = SimpleNamespace(execute=AsyncMock(side_effect=execute))
        result = await _build_coordinator(conversation_log=log, handler=handler).execute_request(
            request
        )
        handler.execute.assert_awaited_once_with(request)
        assert result.response_text == "Train options ready"
    finally:
        await messages.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,session_id,run_id,lookup,record",
    [
        ("no_log", "s1", "r1", False, False),
        ("empty_history", "s1", "r1", True, False),
        ("missing_session", "", "r1", False, False),
        ("missing_run", "s1", "", False, False),
        ("lookup_failure", "s1", "r1", True, False),
        ("record_failure", "s1", "r1", True, True),
    ],
)
async def test_optional_or_failed_dependency_tracking_still_executes_handler(
    case, session_id, run_id, lookup, record
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    log = SimpleNamespace(
        list_visible_message_ids=AsyncMock(
            return_value=[] if case == "empty_history" else ["m1"],
            side_effect=RuntimeError("lookup offline") if case == "lookup_failure" else None,
        ),
        record_consumed=AsyncMock(
            side_effect=RuntimeError("write offline") if case == "record_failure" else None
        ),
    )
    handler = SimpleNamespace(
        execute=AsyncMock(
            return_value=ExecutionResult(mode=None, response_text="Execution completed")
        )
    )
    request = _build_request(_build_context(session_id=session_id, run_id=run_id, revision=2))
    result = await _build_coordinator(
        conversation_log=None if case == "no_log" else log, handler=handler
    ).execute_request(request)
    handler.execute.assert_awaited_once_with(request)
    assert result.response_text == "Execution completed"
    if lookup:
        log.list_visible_message_ids.assert_awaited_once_with(session_id=session_id)
    else:
        log.list_visible_message_ids.assert_not_awaited()
    if record:
        log.record_consumed.assert_awaited_once_with(
            session_id=session_id, run_id=run_id, revision=2, message_ids=["m1"]
        )
    else:
        log.record_consumed.assert_not_awaited()
