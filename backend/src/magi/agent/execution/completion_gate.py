"""Evidence-driven completion gate for the unified agent loop."""

from __future__ import annotations

from .completion_policy import CompletionPolicy
from .contracts import CompletionDecision, CompletionOutcome
from .evidence import (
    ToolExecutionEvidence,
    failed_validation_evidence,
    successful_validation_evidence,
)


class CompletionGate:
    """Decide whether a proposed final response is supported by run evidence."""

    def evaluate(
        self,
        *,
        policy: CompletionPolicy,
        evidence: list[ToolExecutionEvidence],
        repair_iterations: int,
        pending_interaction: bool = False,
    ) -> CompletionDecision:
        refs = tuple(item.to_ref() for item in evidence)
        if pending_interaction:
            return CompletionDecision(
                outcome=CompletionOutcome.SUSPEND,
                reason_code="user_input_required",
                observations=("A required user interaction is still pending.",),
                evidence_refs=refs,
            )

        if policy.require_effect_terminal_state and any(item.uncertain for item in evidence):
            return CompletionDecision(
                outcome=CompletionOutcome.BLOCKED,
                reason_code="uncertain_effect",
                observations=(
                    "An external effect has an uncertain outcome and must be reconciled before completion.",
                ),
                evidence_refs=refs,
            )

        failed_validation = failed_validation_evidence(
            evidence,
            validation_tool_names=policy.validation_tool_names,
        )
        successful_validation = successful_validation_evidence(
            evidence,
            validation_tool_names=policy.validation_tool_names,
        )
        latest_failed_validation_index = max(
            (index for index, item in enumerate(evidence) if item in failed_validation),
            default=-1,
        )
        latest_successful_validation_index = max(
            (index for index, item in enumerate(evidence) if item in successful_validation),
            default=-1,
        )
        if latest_failed_validation_index > latest_successful_validation_index:
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
                suggested_reasoning_floor="medium",
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
        validation_is_current = any(
            index > last_guarded_effect_index and item in successful_validation
            for index, item in enumerate(evidence)
        )
        if last_guarded_effect_index >= 0 and not validation_is_current:
            if repair_iterations >= policy.max_repair_iterations:
                return CompletionDecision(
                    outcome=CompletionOutcome.BLOCKED,
                    reason_code="repair_exhausted",
                    observations=("The run changed local state but never produced validation evidence.",),
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
