from __future__ import annotations

import pytest

from magi.agent.execution.completion_gate import CompletionGate
from magi.agent.execution.completion_policy import CompletionPolicy
from magi.agent.execution.contracts import CompletionOutcome
from magi.agent.execution.evidence import ToolExecutionEvidence
from magi.control.run_plan import apply_plan_mutation


def _validation(
    path: str, status: str = "pass", *, verifier: str = "py_compile", digest: str = "a"
):
    return ToolExecutionEvidence(
        tool_name="verify",
        success=True,
        effect_class="read_only",
        replay_policy="read_only",
        result={
            "summary": {status: 1},
            "results": [
                {
                    "path": path,
                    "status": status,
                    "verifier": verifier,
                    "content_sha256": digest * 64,
                }
            ],
        },
    )


def _write(path: str, digest: str = "a"):
    return ToolExecutionEvidence(
        tool_name="file_write",
        success=True,
        effect_class="local_write",
        replay_policy="reconcilable",
        result={"validation_targets": [{"path": path, "content_sha256": digest * 64}]},
    )


def _evaluate(evidence):
    return CompletionGate().evaluate(
        policy=CompletionPolicy(), evidence=evidence, repair_iterations=0
    )


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"summary": {"pass": 0}, "results": []},
        {"summary": {"pass": 1}, "results": [{"status": "pass"}]},
    ],
)
def test_empty_or_unidentified_validation_is_inconclusive(result) -> None:
    validation = ToolExecutionEvidence(
        tool_name="verify",
        success=True,
        effect_class="read_only",
        replay_policy="read_only",
        result=result,
    )
    assert _evaluate([_write("a.py"), validation]).reason_code == "validation_inconclusive"


@pytest.mark.parametrize(
    "later", [_validation("b.py"), _validation("a.py", verifier="other_check")]
)
def test_unrelated_success_cannot_clear_failed_check(later) -> None:
    assert _evaluate([_validation("a.py", "fail"), later]).reason_code == "validation_failed"


def test_failures_are_resolved_per_target_across_separate_calls() -> None:
    evidence = [_validation("a.py", "fail"), _validation("b.py", "fail"), _validation("b.py")]
    assert _evaluate(evidence).reason_code == "validation_failed"
    assert _evaluate([*evidence, _validation("a.py")]).outcome is CompletionOutcome.COMPLETE


def test_timeout_cannot_erase_a_failed_check() -> None:
    assert (
        _evaluate([_validation("a.py", "fail"), _validation("a.py", "timeout")]).reason_code
        == "validation_failed"
    )


def test_unknown_verifier_can_be_replaced_by_real_check_of_same_path() -> None:
    evidence = [_validation("a.py", "skipped", verifier="(none)")]
    assert _evaluate([*evidence, _validation("b.py")]).reason_code == "validation_inconclusive"
    assert _evaluate([*evidence, _validation("a.py")]).outcome is CompletionOutcome.COMPLETE


def test_validation_must_cover_every_latest_written_content_version() -> None:
    evidence = [_write("a.py"), _validation("a.py"), _write("b.py"), _validation("b.py")]
    assert _evaluate(evidence).outcome is CompletionOutcome.COMPLETE
    evidence.append(_write("a.py", "b"))
    assert _evaluate([*evidence, _validation("b.py")]).reason_code == "validation_required"
    assert _evaluate([*evidence, _validation("a.py")]).reason_code == "validation_required"
    assert (
        _evaluate([*evidence, _validation("a.py", digest="b")]).outcome
        is CompletionOutcome.COMPLETE
    )


def test_validation_of_other_file_cannot_cover_a_write() -> None:
    assert _evaluate([_write("a.py"), _validation("b.py")]).reason_code == "validation_required"


def test_unidentified_pass_cannot_be_repaired_by_another_target() -> None:
    unidentified = ToolExecutionEvidence(
        tool_name="verify", success=True, effect_class="read_only", replay_policy="read_only",
        result={"results": [{"path": "a.py", "status": "pass", "verifier": "py_compile"}]},
    )
    assert _evaluate([unidentified, _validation("b.py")]).reason_code == "validation_inconclusive"
    assert _evaluate([unidentified, _validation("a.py")]).outcome is CompletionOutcome.COMPLETE


def test_unknown_effect_requires_rechecking_declared_files() -> None:
    unknown = ToolExecutionEvidence(
        tool_name="bash", success=True, effect_class="unknown", replay_policy="unknown",
    )
    evidence = [_write("a.py"), _validation("a.py"), unknown, _validation("b.py")]
    assert _evaluate(evidence).reason_code == "validation_required"
    assert _evaluate([*evidence, _validation("a.py")]).outcome is CompletionOutcome.COMPLETE


def test_no_target_verification_after_unknown_effect_cannot_complete() -> None:
    effect = ToolExecutionEvidence(
        tool_name="bash", success=True, effect_class="unknown", replay_policy="unknown"
    )
    empty = ToolExecutionEvidence(
        tool_name="verify",
        success=True,
        effect_class="read_only",
        replay_policy="read_only",
        result={"summary": {"pass": 0, "fail": 0, "skipped": 0, "timeout": 0}, "results": []},
    )
    assert _evaluate([effect, empty]).reason_code == "validation_inconclusive"
    assert _evaluate([effect, empty, _validation("a.py")]).outcome is CompletionOutcome.COMPLETE


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
                result={
                    "summary": {"pass": 1, "fail": 0, "skipped": 0, "timeout": 0},
                    "results": [
                        {
                            "status": "pass",
                            "path": "/workspace/a.py",
                            "verifier": "py_compile",
                            "content_sha256": "a" * 64,
                        }
                    ],
                },
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
                result={
                    "summary": {"pass": 0, "fail": 1, "skipped": 0, "timeout": 0},
                    "results": [
                        {
                            "status": "fail",
                            "path": "/workspace/a.py",
                            "verifier": "py_compile",
                            "content_sha256": "a" * 64,
                        }
                    ],
                },
            )
        ],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.CONTINUE
    assert decision.reason_code == "validation_failed"
    assert decision.reasoning_helpful is True


def test_validation_timeout_requests_repair_without_reasoning_escalation() -> None:
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(),
        evidence=[
            ToolExecutionEvidence(
                tool_name="verify",
                success=True,
                effect_class="read_only",
                replay_policy="read_only",
                result={
                    "summary": {"pass": 0, "fail": 0, "skipped": 0, "timeout": 1},
                    "results": [
                        {
                            "status": "timeout",
                            "path": "/workspace/a.py",
                            "verifier": "py_compile",
                            "content_sha256": "a" * 64,
                        }
                    ],
                },
            )
        ],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.CONTINUE
    assert decision.reason_code == "validation_inconclusive"
    assert decision.reasoning_helpful is False


def test_skipped_validation_does_not_satisfy_local_write_requirement() -> None:
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
                result={
                    "summary": {"pass": 0, "fail": 0, "skipped": 1, "timeout": 0},
                    "results": [
                        {
                            "status": "skipped",
                            "path": "/workspace/a.py",
                            "verifier": "py_compile",
                            "content_sha256": "a" * 64,
                        }
                    ],
                },
            ),
        ],
        repair_iterations=0,
    )

    assert decision.outcome is CompletionOutcome.CONTINUE
    assert decision.reason_code == "validation_inconclusive"
    assert decision.reasoning_helpful is False


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
        result={
            "summary": {"pass": 1},
            "results": [
                {
                    "status": "pass",
                    "path": "/workspace/a.py",
                    "verifier": "py_compile",
                    "content_sha256": "a" * 64,
                }
            ],
        },
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
