from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.execution.contracts import AgentRunEventType
from magi.agent.execution.function_calling.step_models import FunctionCallingStepState
from magi.agent.execution.function_calling.step_tool_batch import (
    FunctionCallingToolBatchExecutor,
)
from magi.agent.execution.function_calling.tool_batch_journal import ToolExecutionRecord
from magi.agent.execution.function_calling.types import ToolCall, ToolCallResult
from magi.agent.execution.journal import AgentRunJournal
from magi.agent.execution.reasoning import ReasoningPolicy, ReasoningPreference, ReasoningState
from magi.control.tools import RequestReasoningDepthTool
from magi.tools.schema import ToolExecutionContext


def _record(reason: str) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        tool_call=ToolCall(
            id="call-1",
            name="request_reasoning_depth",
            arguments={"reason": reason},
        ),
        fingerprint="request-reasoning",
        result=ToolCallResult(
            tool_call_id="call-1",
            tool_name="request_reasoning_depth",
            success=True,
            data={"status": "requested", "reason": reason},
        ),
    )


@pytest.mark.asyncio
async def test_reasoning_depth_tool_returns_a_request_without_self_approval() -> None:
    result = await RequestReasoningDepthTool().execute(
        {"reason": "conflicting_evidence"},
        ToolExecutionContext(agent_id="agent", workspace="/tmp"),
    )

    assert result.success is True
    assert result.data == {
        "status": "requested",
        "reason": "conflicting_evidence",
    }


@pytest.mark.asyncio
async def test_runtime_approves_model_request_within_policy_and_records_event() -> None:
    policy = ReasoningPolicy.from_preference(ReasoningPreference.AUTO)
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="system",
        tools=[],
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
    )
    state.journal = AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
    )
    record = _record("conflicting_evidence")

    await FunctionCallingToolBatchExecutor(SimpleNamespace())._apply_reasoning_depth_request(
        state=state,
        record=record,
        iteration=2,
    )

    assert record.result.data["approved"] is True
    assert record.result.data["status"] == "approved"
    assert record.result.data["requested_depth"] == "high"
    assert record.result.data["visibility"] == "runtime_internal"
    assert record.result.data["next_action"] == "continue_with_approved_depth"
    assert state.reasoning_state.requested_depth.value == "high"
    assert [event.event_type for event in state.journal.events] == [
        AgentRunEventType.REASONING_DEPTH_CHANGED
    ]
    assert state.journal.events[0].payload["request_source"] == "model"


@pytest.mark.asyncio
async def test_auto_reaches_max_after_two_approved_requests() -> None:
    policy = ReasoningPolicy.from_preference(ReasoningPreference.AUTO)
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="system",
        tools=[],
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
    )
    executor = FunctionCallingToolBatchExecutor(SimpleNamespace())
    first = _record("task_complexity")
    second = _record("conflicting_evidence")
    third = _record("stalled_reasoning")

    await executor._apply_reasoning_depth_request(state=state, record=first, iteration=1)
    await executor._apply_reasoning_depth_request(state=state, record=second, iteration=2)
    await executor._apply_reasoning_depth_request(state=state, record=third, iteration=3)

    assert first.result.data["requested_depth"] == "high"
    assert second.result.data["requested_depth"] == "max"
    assert third.result.data["approved"] is False
    assert state.reasoning_state.requested_depth.value == "max"


@pytest.mark.asyncio
async def test_runtime_denies_model_request_at_user_mode_limit() -> None:
    policy = ReasoningPolicy.from_preference(ReasoningPreference.FAST)
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="system",
        tools=[],
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
    )
    executor = FunctionCallingToolBatchExecutor(SimpleNamespace())
    first = _record("task_complexity")
    second = _record("stalled_reasoning")

    await executor._apply_reasoning_depth_request(state=state, record=first, iteration=1)
    await executor._apply_reasoning_depth_request(state=state, record=second, iteration=2)

    assert first.result.data["approved"] is True
    assert first.result.data["requested_depth"] == "low"
    assert second.result.data["approved"] is False
    assert second.result.success is True
    assert second.result.data["status"] == "denied"
    assert second.result.data["denial_reason"] == "policy_or_budget_limit"
    assert second.result.data["visibility"] == "runtime_internal"
    assert second.result.data["next_action"] == "continue_at_current_depth"
    assert state.reasoning_state.requested_depth.value == "low"
