"""Validation and routing rules for L3 reflection candidates."""

from __future__ import annotations

from typing import Any, Iterable

from .models import L3Candidate, TaskOutcomePacket, ValidationDecision

_EXECUTION_TRACE_TERMS = (
    "called ",
    "retried",
    "worker",
    "tool",
    "grep",
    "rg",
    "ripgrep",
)


def validate_candidate(
    candidate: L3Candidate,
    *,
    evidence_events: Iterable[dict[str, Any]],
    task_outcome: TaskOutcomePacket | None = None,
) -> ValidationDecision:
    """Return the minimal routing decision for an L3 candidate."""

    if not candidate.source_event_ids:
        return ValidationDecision(action="reject", reason="missing_evidence")

    evidence = list(evidence_events)
    if not evidence:
        return ValidationDecision(action="reject", reason="missing_evidence")

    if all(str(event.get("retention_class", "")) == "disposable" for event in evidence):
        return ValidationDecision(action="reject", reason="disposable_only")

    if task_outcome is not None and _looks_like_execution_trace(candidate, task_outcome, evidence):
        return ValidationDecision(action="route_to_l4", reason="execution_trace")

    return ValidationDecision(action="accept", reason="accepted")


def _looks_like_execution_trace(
    candidate: L3Candidate,
    task_outcome: TaskOutcomePacket,
    evidence_events: list[dict[str, Any]],
) -> bool:
    combined = " ".join(
        part
        for part in (
            candidate.content.lower(),
            str(task_outcome.result_summary or "").lower(),
            str(task_outcome.task_title or "").lower(),
        )
        if part
    )
    if any(term in combined for term in _EXECUTION_TRACE_TERMS):
        return True
    return bool(evidence_events) and all(str(event.get("memory_domain", "")) == "runtime_telemetry" for event in evidence_events)
