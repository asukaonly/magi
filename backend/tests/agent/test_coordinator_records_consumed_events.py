"""Phase F Task 10: ChatExecutionCoordinator records which messages each
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
from magi.agent.task_agents.handlers.contracts import IntentDecision
from magi.chat.task_agent.fact_classifier import (
    ChatFactClassifier,
    IncomingFactKind,
)
from magi.agent.task_agents.common.contracts import (
    ExecutionRequest,
    ExecutionResult,
    ToolSelection,
)
from magi.events.events import EventTypes


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingLog:
    """Captures every record_consumed call + emits a fixed visible-id list."""

    def __init__(self, visible_ids: list[str]) -> None:
        self._visible = list(visible_ids)
        self.records: list[tuple[str, str, int, list[str]]] = []

    async def list_visible_message_ids(self, *, session_id: str) -> list[str]:
        _ = session_id
        return list(self._visible)

    async def record_consumed(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        message_ids: list[str],
    ) -> None:
        self.records.append(
            (session_id, run_id, int(revision), list(message_ids)),
        )

    # The remaining surface — coordinator never touches these here, but the
    # protocol-like duck shape keeps tests from accidentally type-narrowing.
    async def append(self, ev, *, session_id):
        return None

    async def materialize(self, **kw):
        return []

    async def find_dependents(self, **kw):
        return []


class _RaisingLog(_RecordingLog):
    """list_visible_message_ids raises — coordinator must swallow + skip."""

    async def list_visible_message_ids(self, *, session_id: str) -> list[str]:
        raise RuntimeError("log offline")


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
            dict(fact.payload), fallback_user_id=user_id,
        ),
        session_run_id=run_id,
        session_run_revision=revision,
    )
    return ctx


def _build_request(ctx: ChatRuntimeContext) -> ExecutionRequest:
    intent = IntentDecision(
        intent="chat",
        execution_mode=None,
        reasoning="",
    )
    return ExecutionRequest(
        mode=None,
        context=ctx,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )


def _build_coordinator(*, conversation_log) -> ChatExecutionCoordinator:
    return ChatExecutionCoordinator(
        tool_registry=_FakeToolRegistry(),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        agent_run_handler=_FakeAgentRunHandler(),
        conversation_log=conversation_log,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_records_consumed_message_ids() -> None:
    """When the log is wired and history has visible messages, execute()
    records the run as a consumer of those message_ids."""
    log = _RecordingLog(visible_ids=["m1", "m2", "m3"])
    coord = _build_coordinator(conversation_log=log)

    ctx = _build_context(session_id="s1", run_id="run-1", revision=0)
    await coord.execute(_build_request(ctx))

    assert len(log.records) == 1
    sid, rid, rev, ids = log.records[0]
    assert sid == "s1"
    assert rid == "run-1"
    assert rev == 0
    assert ids == ["m1", "m2", "m3"]


@pytest.mark.asyncio
async def test_execute_uses_context_revision_for_record_consumed() -> None:
    """When the context carries a non-zero revision (updated run), the
    recorded entry tags the same revision so find_dependents differentiates
    pre- vs post-interrupt consumption."""
    log = _RecordingLog(visible_ids=["m1"])
    coord = _build_coordinator(conversation_log=log)

    ctx = _build_context(session_id="s1", run_id="run-1", revision=2)
    await coord.execute(_build_request(ctx))

    _, _, rev, _ = log.records[0]
    assert rev == 2


@pytest.mark.asyncio
async def test_execute_skips_record_consumed_with_no_log() -> None:
    """When conversation_log is None, execute must still
    drive the runner and return a result without crashing."""
    coord = _build_coordinator(conversation_log=None)

    ctx = _build_context(session_id="s1", run_id="run-1")
    result = await coord.execute(_build_request(ctx))
    assert result is not None


@pytest.mark.asyncio
async def test_execute_swallows_log_failure() -> None:
    """A failing log.list_visible_message_ids must not break the run."""
    log = _RaisingLog(visible_ids=[])
    coord = _build_coordinator(conversation_log=log)

    ctx = _build_context(session_id="s1", run_id="run-1")
    # Should NOT raise. No record either (since lookup failed).
    result = await coord.execute(_build_request(ctx))
    assert result is not None
    assert log.records == []


@pytest.mark.asyncio
async def test_execute_skips_record_consumed_when_no_session_or_run_id() -> None:
    """No session_id / run_id → can't record, just drive the runner."""
    log = _RecordingLog(visible_ids=["m1"])
    coord = _build_coordinator(conversation_log=log)

    ctx = _build_context(session_id="", run_id="")
    await coord.execute(_build_request(ctx))
    assert log.records == []


@pytest.mark.asyncio
async def test_execute_skips_record_consumed_when_history_empty() -> None:
    """First-ever turn: nothing to consume, so no record is written."""
    log = _RecordingLog(visible_ids=[])
    coord = _build_coordinator(conversation_log=log)

    ctx = _build_context(session_id="s1", run_id="run-1")
    await coord.execute(_build_request(ctx))
    assert log.records == []
