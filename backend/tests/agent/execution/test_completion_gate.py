from __future__ import annotations

from magi.agent.execution.completion_gate import CompletionGate
from magi.agent.execution.completion_policy import CompletionPolicy
from magi.agent.execution.contracts import CompletionOutcome
from magi.agent.execution.evidence import ToolExecutionEvidence
from magi.control.run_plan import apply_plan_mutation


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


def test_required_plan_blocks_completion_while_todo_is_pending() -> None:
    plan = apply_plan_mutation(
        None,
        session_id="session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        required=True,
        status=None,
        item_mutations=[{"content": "Verify behavior"}],
    )

    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[],
        repair_iterations=0,
        run_plan=plan,
    )

    assert decision.outcome is CompletionOutcome.CONTINUE
    assert decision.reason_code == "required_plan_incomplete"


def test_completed_required_todo_must_reference_current_run_evidence() -> None:
    evidence = ToolExecutionEvidence(
        evidence_id="evidence-1",
        tool_name="verify",
        success=True,
        effect_class="read_only",
        replay_policy="read_only",
        result={"summary": {"failed": 0}},
    )
    plan = apply_plan_mutation(
        None,
        session_id="session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        required=True,
        status=None,
        item_mutations=[
            {
                "content": "Verify behavior",
                "status": "completed",
                "evidence_refs": ["different-run"],
            }
        ],
    )
    rejected = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[evidence],
        repair_iterations=0,
        run_plan=plan,
    )
    assert rejected.reason_code == "todo_evidence_missing"

    grounded = apply_plan_mutation(
        None,
        session_id="session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        required=True,
        status=None,
        item_mutations=[
            {
                "content": "Verify behavior",
                "status": "completed",
                "evidence_refs": ["evidence-1"],
            }
        ],
    )
    accepted = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[evidence],
        repair_iterations=0,
        run_plan=grounded,
    )
    assert accepted.outcome is CompletionOutcome.COMPLETE


def test_plan_completion_rejects_failed_and_governance_only_evidence() -> None:
    plan = apply_plan_mutation(
        None,
        session_id="session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        required=True,
        status=None,
        item_mutations=[
            {
                "content": "Make the requested change",
                "status": "completed",
                "evidence_refs": ["todo-evidence", "failed-evidence"],
            }
        ],
    )
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[
            ToolExecutionEvidence(
                evidence_id="todo-evidence",
                tool_name="todo_write",
                success=True,
                effect_class="external_write",
                replay_policy="reconcilable",
            ),
            ToolExecutionEvidence(
                evidence_id="failed-evidence",
                tool_name="file_edit",
                success=False,
                effect_class="local_write",
                replay_policy="reconcilable",
            ),
        ],
        repair_iterations=0,
        run_plan=plan,
    )

    assert decision.outcome is CompletionOutcome.CONTINUE
    assert decision.reason_code == "todo_evidence_missing"
