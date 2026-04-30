"""Shadow-evaluation records for hybrid retrieval intent decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .llm_intent import LLMRefinement
from .models import IntentDecision


@dataclass
class EvaluationRecord:
    """Shadow evaluation record for logging."""

    query: str
    user_id: Optional[str]
    session_id: Optional[str]
    rule_decision: IntentDecision
    llm_refinement: Optional[LLMRefinement]
    final_decision: IntentDecision
    decision_source: str
    llm_latency_ms: Optional[float]
    llm_error: Optional[str]
    refinement_applied: bool
    diff_summary: str


def compute_diff(
    rule_decision: IntentDecision,
    llm_refinement: Optional[LLMRefinement],
) -> tuple[bool, str]:
    """Summarise whether the LLM produced a usable refinement."""
    if llm_refinement is None:
        return False, "llm_failed"

    parts: list[str] = []
    rule_content_query = (
        rule_decision.plans[0].conditions.content_query if rule_decision.plans else ""
    )
    if llm_refinement.content_query and llm_refinement.content_query != rule_content_query:
        parts.append("content_query")
    if llm_refinement.entities is not None:
        parts.append("entities")
    if llm_refinement.subject_hint is not None:
        parts.append("subject_hint")
    if llm_refinement.predicate_family is not None:
        parts.append("predicate_family")
    if llm_refinement.semantic_frame is not None:
        parts.append("semantic_frame")
    summary = "applied: " + ",".join(parts) if parts else "applied: empty"
    return True, summary


__all__ = ["EvaluationRecord", "compute_diff"]
