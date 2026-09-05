"""Evidence-driven completion gate for the unified agent loop."""

from __future__ import annotations

from .completion_policy import CompletionPolicy
from .contracts import CompletionDecision, CompletionOutcome
from .evidence import (
    ToolExecutionEvidence,
    failed_validation_evidence,
    inconclusive_validation_evidence,
    successful_validation_evidence,
    unresolved_validations,
    validation_checks,
)
from magi.control.run_plan import PlanStatus, RunPlan, TodoStatus


class CompletionGate:
    """Decide whether a proposed final response is supported by run evidence."""

    def evaluate(
        self,
        *,
        policy: CompletionPolicy,
        evidence: list[ToolExecutionEvidence],
        repair_iterations: int,
        run_plan: RunPlan | None = None,
    ) -> CompletionDecision:
        refs = tuple(item.to_ref() for item in evidence)
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
        )
        if plan_decision is not None:
            return plan_decision

        failed_validation = failed_validation_evidence(
            evidence,
            validation_tool_names=policy.validation_tool_names,
        )
        successful_validation = successful_validation_evidence(
            evidence,
            validation_tool_names=policy.validation_tool_names,
        )
        inconclusive_validation = inconclusive_validation_evidence(
            evidence,
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

        local_writes = [
            item for item in evidence if item.success and item.effect_class == "local_write"
        ]
        unknown_effects = [
            item for item in evidence if item.success and item.effect_class == "unknown"
        ]
        guarded_effects = [
            *(local_writes if policy.require_local_write_validation else []),
            *(unknown_effects if policy.require_unknown_effect_validation else []),
        ]
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


def _effects_have_current_validation(
    evidence: list[ToolExecutionEvidence],
    guarded_effects: list[ToolExecutionEvidence],
    successful_validation: list[ToolExecutionEvidence],
) -> bool:
    targets: dict[str, tuple[int, str | None]] = {}
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
            targets[str(target["path"])] = (index, target.get("content_sha256"))
    checks = [
        (index, row)
        for index, item in enumerate(evidence)
        if item in successful_validation
        for row in validation_checks(item)
    ]
    last_unscoped_effect = max(unscoped_effects, default=-1)
    return all(
        any(index > effect_index for index, _ in checks) for effect_index in unscoped_effects
    ) and all(
        digest is not None
        and any(
            index > max(effect_index, last_unscoped_effect)
            and row.get("path") == path
            and row.get("content_sha256") == digest
            for index, row in checks
        )
        for path, (effect_index, digest) in targets.items()
    )


def _evaluate_required_plan(
    plan: RunPlan | None,
    *,
    evidence: list[ToolExecutionEvidence],
    repair_iterations: int,
    max_repair_iterations: int,
    refs,
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

    available_refs = {
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
                "Attach an evidence_ref from this run to every completed required todo.",
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
