"""Evidence-driven completion gate for the unified agent loop."""

from __future__ import annotations

from .completion_policy import CompletionPolicy
from .contracts import CompletionDecision, CompletionOutcome
from .evidence import (
    ToolExecutionEvidence,
    failed_validation_evidence,
    has_inline_validation,
    inconclusive_validation_evidence,
    successful_validation_evidence,
    text_evidence_ref,
    unresolved_validations,
    validation_checks,
)
from magi.control.run_plan import (
    FINAL_RESPONSE_EVIDENCE_REF,
    USER_INPUT_EVIDENCE_REF,
    PlanStatus,
    RunPlan,
    TodoStatus,
)


class CompletionGate:
    """Decide whether a proposed final response is supported by run evidence."""

    def evaluate(
        self,
        *,
        policy: CompletionPolicy,
        evidence: list[ToolExecutionEvidence],
        repair_iterations: int,
        run_plan: RunPlan | None = None,
        user_input: str = "",
        final_response: str = "",
    ) -> CompletionDecision:
        text_refs = tuple(
            text_evidence_ref(reference, text)
            for reference, text in (
                (USER_INPUT_EVIDENCE_REF, user_input),
                (FINAL_RESPONSE_EVIDENCE_REF, final_response),
            ) if text.strip()
        )
        refs = (*tuple(item.to_ref() for item in evidence), *text_refs)
        if policy.require_effect_terminal_state and any(item.uncertain for item in evidence):
            return CompletionDecision(
                outcome=CompletionOutcome.BLOCKED,
                reason_code="uncertain_effect",
                observations=(
                    "An external effect has an uncertain outcome and must be reconciled before completion.",
                ),
                evidence_refs=refs,
            )

        pending_jobs = _pending_shell_jobs(evidence)
        if pending_jobs:
            exhausted = repair_iterations >= policy.max_repair_iterations
            return CompletionDecision(
                outcome=CompletionOutcome.BLOCKED if exhausted else CompletionOutcome.CONTINUE,
                reason_code="shell_job_pending",
                observations=(
                    "A foreground command is still running. Use shell_job to wait for its result, "
                    "or explicitly stop it before reporting a final outcome. Job IDs: "
                    + ", ".join(sorted(pending_jobs)),
                ),
                evidence_refs=refs,
                repairable=not exhausted,
            )

        plan_decision = _evaluate_required_plan(
            run_plan,
            evidence=evidence,
            repair_iterations=repair_iterations,
            max_repair_iterations=policy.max_repair_iterations,
            refs=refs,
            text_refs={item.evidence_id for item in text_refs},
        )
        if plan_decision is not None:
            return plan_decision

        guarded_effects = [
            item for item in evidence
            if item.success and not _rollback_without_changes(item)
            and not _confirmed_shell_effect(item, evidence) and (
                (item.effect_class == "local_write" and policy.require_local_write_validation)
                or (
                    item.effect_class == "unknown"
                    and policy.require_unknown_effect_validation
                )
            )
        ]
        first_mutation = next(
            (index for index, item in enumerate(evidence) if _mutating_effect(item, evidence)),
            len(evidence),
        )
        # A command exit needs no invented file check, but an actual failed check
        # after a mutation remains actionable evidence.
        validation_after_mutation = [
            item for index, item in enumerate(evidence)
            if index > first_mutation or (index == first_mutation and has_inline_validation(item))
        ]
        failed_validation = failed_validation_evidence(
            validation_after_mutation,
            validation_tool_names=policy.validation_tool_names,
        )
        successful_validation = successful_validation_evidence(
            evidence,
            validation_tool_names=policy.validation_tool_names,
        )
        inconclusive_validation = inconclusive_validation_evidence(
            validation_after_mutation,
            validation_tool_names=policy.validation_tool_names,
        )
        if unresolved_validations(failed_validation, evidence, successful_validation):
            if repair_iterations >= policy.max_repair_iterations:
                return CompletionDecision(
                    outcome=CompletionOutcome.BLOCKED,
                    reason_code="repair_exhausted",
                    observations=("Validation still fails after the repair budget was exhausted.",),
                    evidence_refs=refs,
                )
            return CompletionDecision(
                outcome=CompletionOutcome.CONTINUE,
                reason_code="validation_failed",
                observations=(
                    "Validation failed. Inspect the validation evidence, repair the change, and validate again.",
                ),
                evidence_refs=refs,
                repairable=True,
                reasoning_helpful=True,
            )
        if unresolved_validations(inconclusive_validation, evidence, successful_validation):
            if repair_iterations >= policy.max_repair_iterations:
                return CompletionDecision(
                    outcome=CompletionOutcome.BLOCKED,
                    reason_code="repair_exhausted",
                    observations=(
                        "Validation remained inconclusive after the repair budget was exhausted.",
                    ),
                    evidence_refs=refs,
                )
            return CompletionDecision(
                outcome=CompletionOutcome.CONTINUE,
                reason_code="validation_inconclusive",
                observations=(
                    "Validation checked no targets, skipped a target, timed out, or lacked content identity. Verify every affected target with a supported check.",
                ),
                evidence_refs=refs,
                repairable=True,
                reasoning_helpful=False,
            )

        last_guarded_effect_index = max(
            (index for index, item in enumerate(evidence) if item in guarded_effects),
            default=-1,
        )
        validation_is_current = _effects_have_current_validation(
            evidence,
            guarded_effects,
            successful_validation,
        )
        if last_guarded_effect_index >= 0 and not validation_is_current:
            if repair_iterations >= policy.max_repair_iterations:
                return CompletionDecision(
                    outcome=CompletionOutcome.BLOCKED,
                    reason_code="repair_exhausted",
                    observations=(
                        "The run changed local state but never produced validation evidence.",
                    ),
                    evidence_refs=refs,
                )
            return CompletionDecision(
                outcome=CompletionOutcome.CONTINUE,
                reason_code="validation_required",
                observations=(
                    "The run changed state or used an unknown-effect capability. Run an appropriate verification step after the latest effect before presenting a final answer.",
                ),
                evidence_refs=refs,
                repairable=True,
                reasoning_helpful=False,
            )

        return CompletionDecision(
            outcome=CompletionOutcome.COMPLETE,
            reason_code="evidence_satisfied",
            evidence_refs=refs,
        )


__all__ = ["CompletionGate"]


def _completed_command(item: ToolExecutionEvidence) -> bool:
    """Accept an actual shell exit receipt, without claiming file integrity."""
    if item.tool_name not in {"bash", "powershell", "shell_job"} or not isinstance(item.result, dict):
        return False
    if item.tool_name == "shell_job" and (
        item.result.get("shell_tool") not in {"bash", "powershell"}
        or item.result.get("status") != "completed"
    ):
        return False
    code = item.result.get("return_code")
    return (
        item.success
        and item.result.get("status") not in {"starting", "running", "cancelled", "failed"}
        and type(code) is int
        and item.result.get("command_succeeded") is (code == 0)
        and item.result.get("timed_out") is False
    )


def _confirmed_shell_control(item: ToolExecutionEvidence) -> bool:
    if not item.success or not isinstance(item.result, dict) or not item.result.get("job_id"):
        return False
    if item.tool_name in {"bash", "powershell"}:
        return item.result.get("background_requested") is True and item.result.get("status") == "running"
    return (
        item.tool_name == "shell_job" and item.result.get("shell_tool") in {"bash", "powershell"}
        and item.result.get("action") == "stop" and item.result.get("status") == "cancelled"
        and item.result.get("stopped") is True
    )


def _pending_shell_jobs(evidence: list[ToolExecutionEvidence]) -> set[str]:
    pending: dict[str, str] = {}
    for item in evidence:
        if not item.success or not isinstance(item.result, dict):
            continue
        job_id = item.result.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            continue
        if item.tool_name in {"bash", "powershell"} and item.result.get("status") in {"starting", "running"}:
            if not _confirmed_shell_control(item):
                pending[job_id] = item.tool_name
        elif item.tool_name == "shell_job" and pending.get(job_id) == item.result.get("shell_tool"):
            if _completed_command(item) or _confirmed_shell_control(item):
                pending.pop(job_id)
    return set(pending)


def _confirmed_shell_effect(item: ToolExecutionEvidence, evidence: list[ToolExecutionEvidence]) -> bool:
    if _completed_command(item) or _confirmed_shell_control(item):
        return True
    if item.tool_name not in {"bash", "powershell"} or not isinstance(item.result, dict):
        return False
    job_id = item.result.get("job_id")
    return bool(
        job_id and item.result.get("status") in {"starting", "running"}
        and job_id not in _pending_shell_jobs(evidence)
    )


def _rollback_without_changes(item: ToolExecutionEvidence) -> bool:
    return (
        item.tool_name == "file_rollback" and isinstance(item.result, dict)
        and (item.result.get("dry_run") is True or item.result.get("restored") == [])
    )


def _mutating_effect(item: ToolExecutionEvidence, evidence: list[ToolExecutionEvidence]) -> bool:
    if not item.success or _rollback_without_changes(item):
        return False
    if item.tool_name == "shell_job":
        if not (_completed_command(item) or _confirmed_shell_control(item)):
            return False
        return any(
            other.success and other.tool_name == item.result.get("shell_tool")
            and other.effect_class in {"local_write", "unknown"}
            and isinstance(other.result, dict)
            and other.result.get("job_id") == item.result.get("job_id")
            and other.result.get("risk_level") != "read_only"
            for other in evidence
        )
    if item.tool_name in {"bash", "powershell"} and isinstance(item.result, dict):
        if item.result.get("risk_level") == "read_only":
            return False
    return item.effect_class in {"local_write", "unknown"}


def _has_later_mutation(evidence: list[ToolExecutionEvidence], start: int, end: int, path: str) -> bool:
    for item in evidence[start + 1 : end]:
        if not _mutating_effect(item, evidence):
            continue
        targets = item.result.get("validation_targets") if isinstance(item.result, dict) else None
        if not targets or any(isinstance(target, dict) and target.get("path") == path for target in targets):
            return True
    return False


def _effects_have_current_validation(
    evidence: list[ToolExecutionEvidence],
    guarded_effects: list[ToolExecutionEvidence],
    successful_validation: list[ToolExecutionEvidence],
) -> bool:
    targets: dict[str, tuple[int, dict]] = {}
    unscoped_effects: list[int] = []
    for index, item in enumerate(evidence):
        if item not in guarded_effects:
            continue
        declared = item.result.get("validation_targets") if isinstance(item.result, dict) else None
        if not isinstance(declared, list) or not declared:
            unscoped_effects.append(index)
            continue
        for target in declared:
            if not isinstance(target, dict) or not target.get("path"):
                return False
            targets[str(target["path"])] = (index, target)
    checks = [
        (index, row)
        for index, item in enumerate(evidence)
        if item in successful_validation
        for row in validation_checks(item)
    ]
    # A completed command may still alter a file declared by an earlier write.
    last_unscoped_effect = max(
        [*unscoped_effects, *(
            index for index, item in enumerate(evidence)
            if _mutating_effect(item, evidence)
            and (_completed_command(item) or _confirmed_shell_control(item))
        )],
        default=-1,
    )
    return all(
        any(
            index > effect_index and not has_inline_validation(evidence[index])
            for index, _ in checks
        ) for effect_index in unscoped_effects
    ) and all(
        any(
            row.get("path") == path
            and (
                (
                    target.get("expected_state") == "saved"
                    and row.get("verifier") == "settings.readback"
                    and row.get("matched") is True
                    and index == effect_index
                    and has_inline_validation(evidence[index])
                )
                or (
                    target.get("content_sha256") is not None
                    and row.get("content_sha256") is not None
                    and (
                        row.get("content_sha256") == target["content_sha256"]
                        or _has_later_mutation(evidence, effect_index, index, path)
                    )
                    and index > last_unscoped_effect
                    and (
                        index > effect_index
                        or (index == effect_index and evidence[index].tool_name == "file_rollback")
                    )
                )
                or (
                    row.get("check_kind") == "absence"
                    and index > max(effect_index, last_unscoped_effect)
                    and _has_later_mutation(evidence, effect_index, index, path)
                )
            )
            for index, row in checks
        )
        for path, (effect_index, target) in targets.items()
    )


def _evaluate_required_plan(
    plan: RunPlan | None,
    *,
    evidence: list[ToolExecutionEvidence],
    repair_iterations: int,
    max_repair_iterations: int,
    refs,
    text_refs: set[str],
) -> CompletionDecision | None:
    if plan is None or not plan.required:
        return None
    if plan.status in {PlanStatus.BLOCKED, PlanStatus.CANCELLED}:
        return CompletionDecision(
            outcome=CompletionOutcome.BLOCKED,
            reason_code=f"plan_{plan.status.value}",
            observations=(f"Required plan is {plan.status.value}.",),
            evidence_refs=refs,
        )

    incomplete = [
        item for item in plan.items if item.required and item.status is not TodoStatus.COMPLETED
    ]
    if incomplete:
        if repair_iterations >= max_repair_iterations:
            return CompletionDecision(
                outcome=CompletionOutcome.BLOCKED,
                reason_code="required_plan_incomplete",
                observations=("Required plan items remain incomplete.",),
                evidence_refs=refs,
            )
        return CompletionDecision(
            outcome=CompletionOutcome.CONTINUE,
            reason_code="required_plan_incomplete",
            observations=(
                "Complete or explicitly block every required plan item before finishing.",
            ),
            evidence_refs=refs,
            repairable=True,
        )

    available_refs = text_refs | {
        reference
        for item in evidence
        if item.success and item.tool_name not in _PLAN_GOVERNANCE_TOOLS
        for reference in (item.evidence_id, item.tool_call_id)
        if reference
    }
    ungrounded = [
        item.id
        for item in plan.items
        if item.required
        and item.status is TodoStatus.COMPLETED
        and not available_refs.intersection(item.evidence_refs)
    ]
    if ungrounded:
        if repair_iterations >= max_repair_iterations:
            return CompletionDecision(
                outcome=CompletionOutcome.BLOCKED,
                reason_code="todo_evidence_missing",
                observations=("Required completed todos lack matching run evidence.",),
                evidence_refs=refs,
            )
        return CompletionDecision(
            outcome=CompletionOutcome.CONTINUE,
            reason_code="todo_evidence_missing",
            observations=(
                "Attach a tool evidence_ref, user_input, or final_response from this run to every completed required todo.",
            ),
            evidence_refs=refs,
            repairable=True,
        )
    return None


_PLAN_GOVERNANCE_TOOLS = frozenset(
    {
        "todo_write",
        "enter_plan_mode",
        "exit_plan_mode",
        "ask_user_question",
        "capabilities",
        "get-capabilities",
        "find-relevant-tools",
    }
)
