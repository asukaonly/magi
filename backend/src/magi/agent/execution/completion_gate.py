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
            if item.success and not _rollback_without_changes(item) and (
                (item.effect_class == "local_write" and policy.require_local_write_validation)
                or (
                    item.effect_class == "unknown"
                    and policy.require_unknown_effect_validation
                    and not _completed_command(item)
                )
            )
        ]
        failed_validation = failed_validation_evidence(
            evidence if guarded_effects else [],
            validation_tool_names=policy.validation_tool_names,
        )
        successful_validation = successful_validation_evidence(
            evidence,
            validation_tool_names=policy.validation_tool_names,
        )
        inconclusive_validation = inconclusive_validation_evidence(
            evidence if guarded_effects else [],
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
    if item.tool_name not in {"bash", "powershell"} or not isinstance(item.result, dict):
        return False
    code = item.result.get("return_code")
    return (
        item.success
        and type(code) is int
        and item.result.get("command_succeeded") is (code == 0)
        and item.result.get("timed_out") is False
    )


def _rollback_without_changes(item: ToolExecutionEvidence) -> bool:
    return (
        item.tool_name == "file_rollback" and isinstance(item.result, dict)
        and (item.result.get("dry_run") is True or item.result.get("restored") == [])
    )


def _has_later_mutation(evidence: list[ToolExecutionEvidence], start: int, end: int, path: str) -> bool:
    for item in evidence[start + 1 : end]:
        if not item.success or item.effect_class not in {"local_write", "unknown"} or _rollback_without_changes(item):
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
            index for index, item in enumerate(evidence) if _completed_command(item)
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
                    and row.get("content_sha256") == target["content_sha256"]
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
