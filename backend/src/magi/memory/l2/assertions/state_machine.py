"""Shared validation-state derivation for ToM assertion writes and reconcile."""

from __future__ import annotations

from typing import Optional

_TEMPORARY_STATE_TRAITS = frozenset({"stress_level", "mood", "engagement"})


def compute_confidence(evidence_count: int) -> float:
    """Base confidence curve from accumulated evidence count."""
    return min(0.95, 0.3 + 0.25 * max(0, evidence_count - 1))


def derive_validation_state(
    *,
    current_state: str,
    current_confidence: float,
    evidence_count: int,
    time_span_hours: float,
    trait_name: str,
    user_feedback: Optional[str] = None,
) -> tuple[str, float, str]:
    """Single source of truth for assertion (status, confidence, stability_kind).

    Mirrors the previous ``_derive_reconcile_state`` so write and reconcile paths
    agree on when an assertion graduates from tentative → corroborated → stable.
    """
    is_temporary = trait_name in _TEMPORARY_STATE_TRAITS

    if user_feedback == "rejected":
        return ("user_rejected", 0.10, "volatile_pattern")

    if user_feedback == "confirmed":
        stability_kind = "temporary_state" if is_temporary else "stable_trait"
        return ("stable", max(current_confidence, 0.85), stability_kind)

    if current_state == "contradicted":
        return ("contradicted", min(current_confidence, 0.35), "volatile_pattern")

    if is_temporary:
        if evidence_count >= 3 and time_span_hours >= 24.0:
            return ("stable", max(current_confidence, 0.82), "temporary_state")
        if evidence_count >= 1:
            return ("corroborated", max(current_confidence, 0.50), "temporary_state")

    if evidence_count >= 3 and time_span_hours >= 24.0:
        return ("stable", max(current_confidence, 0.82), "stable_trait")

    if evidence_count >= 2:
        return ("corroborated", max(current_confidence, 0.58), "volatile_pattern")

    return ("tentative", min(current_confidence, 0.3), "volatile_pattern")


__all__ = [
    "compute_confidence",
    "derive_validation_state",
    "_TEMPORARY_STATE_TRAITS",
]
