from __future__ import annotations

from magi.agent.execution.completion_gate import CompletionGate
from magi.agent.execution.completion_policy import CompletionPolicy
from magi.agent.execution.contracts import CompletionOutcome
from magi.agent.execution.evidence import ToolExecutionEvidence


def test_chat_without_effects_completes() -> None:
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.COMPLETE
    assert decision.reason_code == "evidence_satisfied"


def test_local_write_requires_validation() -> None:
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[
            ToolExecutionEvidence(
                tool_name="file_edit",
                success=True,
                effect_class="local_write",
                replay_policy="reconcilable",
            )
        ],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.CONTINUE
    assert decision.reason_code == "validation_required"
    assert decision.repairable is True
    assert decision.reasoning_helpful is False


def test_successful_validation_allows_local_write_completion() -> None:
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[
            ToolExecutionEvidence(
                tool_name="file_edit",
                success=True,
                effect_class="local_write",
                replay_policy="reconcilable",
            ),
            ToolExecutionEvidence(
                tool_name="verify",
                success=True,
                effect_class="read_only",
                replay_policy="read_only",
                result={"summary": {"failed": 0}},
            ),
        ],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.COMPLETE


def test_failed_validation_requests_reasoning_helpful_repair() -> None:
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[
            ToolExecutionEvidence(
                tool_name="verify",
                success=True,
                effect_class="read_only",
                replay_policy="read_only",
                result={"summary": {"failed": 1}},
            )
        ],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.CONTINUE
    assert decision.reason_code == "validation_failed"
    assert decision.reasoning_helpful is True
    assert decision.suggested_reasoning_floor == "medium"


def test_uncertain_effect_blocks_without_retry() -> None:
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[
            ToolExecutionEvidence(
                tool_name="send_message",
                success=False,
                effect_class="external_write",
                replay_policy="non_idempotent",
                error_code="TOOL_EFFECT_UNCERTAIN",
            )
        ],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.BLOCKED
    assert decision.reason_code == "uncertain_effect"
    assert decision.reasoning_helpful is False


def test_repair_budget_is_terminal() -> None:
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(max_repair_iterations=1),
        evidence=[
            ToolExecutionEvidence(
                tool_name="file_write",
                success=True,
                effect_class="local_write",
                replay_policy="reconcilable",
            )
        ],
        repair_iterations=1,
    )

    assert decision.outcome is CompletionOutcome.BLOCKED
    assert decision.reason_code == "repair_exhausted"
