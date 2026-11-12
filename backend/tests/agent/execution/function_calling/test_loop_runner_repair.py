from __future__ import annotations

import pytest

from magi.agent.execution.completion_policy import CompletionPolicy
from magi.runtime_trace.run_events import AgentRunEventType
from magi.agent.execution.evidence import ToolExecutionEvidence
from magi.agent.execution.function_calling.loop_runner import FunctionCallingLoopRunner
from magi.agent.execution.function_calling.run_input import AgentRunRequest
from magi.agent.execution.function_calling.step_models import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
)
from magi.agent.execution.journal import AgentRunJournal
from magi.agent.execution.reasoning import ReasoningPolicy, ReasoningState
from magi.agent.turn_input import UserTurnInput
from magi.context.prompt_lifecycle import DEFAULT_HEADLESS_SYSTEM_PROMPT


def _verify_evidence(status: str) -> ToolExecutionEvidence:
    summary = {"pass": 0, "fail": 0, "skipped": 0, "timeout": 0}
    summary[status] = 1
    return ToolExecutionEvidence(
        tool_name="verify",
        success=True,
        effect_class="read_only",
        replay_policy="read_only",
        result={
            "summary": summary,
            "results": [
                {
                    "status": status,
                    "path": "src/a.py",
                    "verifier": "python",
                    "content_sha256": "a" * 64,
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_failed_validation_uses_auto_escalation_step() -> None:
    policy = ReasoningPolicy()
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="system",
        tools=[],
        iteration=1,
        tool_evidence=[ToolExecutionEvidence(tool_name="file_write", success=True, effect_class="local_write", replay_policy="reconcilable"), _verify_evidence("fail")],
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
    )
    state.journal = AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
    )
    run_input = AgentRunRequest(
        turn=UserTurnInput(text="finish the change"),
        system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
        selected_tools=[],
        user_id="user-1",
        reasoning_policy=policy,
    )

    outcome = await FunctionCallingLoopRunner(object())._evaluate_proposed_final(
        state=state,
        step_outcome=FunctionCallingStepOutcome(
            status="completed",
            iteration=1,
            content="done",
        ),
        run_input=run_input,
    )

    assert outcome is None
    assert state.reasoning_state.requested_depth.value == "high"
    assert AgentRunEventType.REASONING_DEPTH_CHANGED in {
        event.event_type for event in state.journal.events
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("validation_status", ["timeout", "pass"])
async def test_validation_timeout_alone_requires_repair_without_escalation(
    validation_status,
) -> None:
    policy = ReasoningPolicy()
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="system",
        tools=[],
        iteration=1,
        tool_evidence=[ToolExecutionEvidence(tool_name="file_write", success=True, effect_class="local_write", replay_policy="reconcilable"), _verify_evidence(validation_status)],
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
    )
    state.journal = AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
    )
    run_input = AgentRunRequest(
        turn=UserTurnInput(text="finish the change"),
        system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
        selected_tools=[],
        user_id="user-1",
        reasoning_policy=policy,
    )

    outcome = await FunctionCallingLoopRunner(object())._evaluate_proposed_final(
        state=state,
        step_outcome=FunctionCallingStepOutcome(
            status="completed",
            iteration=1,
            content="done",
        ),
        run_input=run_input,
    )

    if validation_status == "timeout":
        assert outcome is None
        assert state.repair_iterations == 1
    else:
        assert outcome is not None and outcome.status == "completed"
        assert state.repair_iterations == 0
    assert state.reasoning_state.requested_depth.value == "low"
    assert AgentRunEventType.REASONING_DEPTH_CHANGED not in {
        event.event_type for event in state.journal.events
    }


@pytest.mark.asyncio
async def test_repair_exhaustion_is_recorded_before_blocking() -> None:
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="system",
        tools=[],
        iteration=2,
        repair_iterations=1,
        tool_evidence=[
            ToolExecutionEvidence(
                tool_name="file_write",
                success=True,
                effect_class="local_write",
                replay_policy="reconcilable",
            )
        ],
        reasoning_state=ReasoningState.start(ReasoningPolicy()),
    )
    state.journal = AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
    )
    run_input = AgentRunRequest(
        turn=UserTurnInput(text="finish the change"),
        system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
        selected_tools=[],
        user_id="user-1",
        completion_policy=CompletionPolicy(max_repair_iterations=1),
    )

    outcome = await FunctionCallingLoopRunner(object())._evaluate_proposed_final(
        state=state,
        step_outcome=FunctionCallingStepOutcome(
            status="completed",
            iteration=2,
            content="done",
        ),
        run_input=run_input,
    )

    assert outcome is not None
    assert outcome.status == "blocked"
    assert outcome.failure_reason == "repair_exhausted"
    assert "done" in outcome.content
    assert "completion not verified" in outcome.content
    assert [event.event_type for event in state.journal.events] == [
        AgentRunEventType.COMPLETION_REQUESTED,
        AgentRunEventType.COMPLETION_REJECTED,
        AgentRunEventType.REPAIR_EXHAUSTED,
    ]


@pytest.mark.asyncio
async def test_budget_finalization_preserves_partial_failure_explanation() -> None:
    from magi.agent.execution.function_calling.types import ExecutionOutcome

    state = FunctionCallingStepState(
        messages=[], effective_system_prompt="system", tools=[],
        tool_evidence=[ToolExecutionEvidence(
            tool_name="file_write", success=True, effect_class="local_write", replay_policy="reconcilable"
        )],
    )
    run_input = AgentRunRequest(
        turn=UserTurnInput(text="finish the change"), system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
        selected_tools=[], user_id="user-1",
    )
    result = await FunctionCallingLoopRunner(object())._gate_fallback_outcome(
        state, run_input,
        ExecutionOutcome(status="completed", content="Saved the draft, but the checker is unavailable.", iterations=2),
    )
    assert result.status == "failed"
    assert result.failure_reason == "repair_budget_unavailable"
    assert "checker is unavailable" in result.content
    assert "completion not verified" in result.content


@pytest.mark.asyncio
async def test_text_only_plan_can_complete_through_loop_without_tool_evidence() -> None:
    from types import SimpleNamespace
    from magi.control.run_plan import apply_plan_mutation

    plan = apply_plan_mutation(
        None, session_id="s1", run_id="r1", plan_id=None, expected_version=0,
        required=True, status=None, item_mutations=[
            {"content": "Use the supplied facts", "status": "completed", "evidence_refs": ["user_input"]},
            {"content": "Write the explanation", "status": "completed", "evidence_refs": ["final_response"]},
        ],
    )
    run_input = AgentRunRequest(
        turn=UserTurnInput(text="Explain these supplied facts."),
        system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT, selected_tools=[], user_id="u1",
        run_plan_reader=SimpleNamespace(current=lambda: plan),
    )
    result = await FunctionCallingLoopRunner(object())._evaluate_proposed_final(
        state=FunctionCallingStepState(messages=[], effective_system_prompt="system", tools=[]),
        step_outcome=FunctionCallingStepOutcome(status="completed", iteration=1, content="The explanation."),
        run_input=run_input,
    )
    assert result.status == "completed"
    assert result.content == "The explanation."
