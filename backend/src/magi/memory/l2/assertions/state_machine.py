"""Shared validation-state derivation for ToM assertion writes and reconcile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .settings import (
    CONFIDENCE_BASE,
    CONFIDENCE_CEILING,
    CONFIDENCE_SLOPE,
    CORROBORATED_CONFIDENCE_FLOOR,
    CORROBORATED_EVIDENCE_COUNT,
    CONTRADICTED_CONFIDENCE_CEILING,
    EXPIRED_CONFIDENCE_CEILING,
    STABLE_CONFIDENCE_FLOOR,
    STABLE_EVIDENCE_COUNT,
    STABLE_TIME_SPAN_HOURS,
    TEMPORARY_CORROBORATED_CONFIDENCE_FLOOR,
    TENTATIVE_CONFIDENCE_CEILING,
    USER_CONFIRMED_CONFIDENCE_FLOOR,
    USER_REJECTED_CONFIDENCE,
    assertion_float_setting,
    assertion_int_setting,
)

_TEMPORARY_STATE_TRAITS = frozenset({"stress_level", "mood", "engagement"})

# Validation states representing live, retrievable assertions. These are the only
# non-terminal states `derive_validation_state` emits — read paths must allow
# exactly these (plus history below), never phantom values like "active".
ACTIVE_VALIDATION_STATES: tuple[str, ...] = ("tentative", "corroborated", "stable")

# Live states plus historically-true-but-replaced facts, surfaced only for
# time-scoped ("as_of"/"during"/...) queries.
HISTORICAL_VALIDATION_STATES: tuple[str, ...] = ACTIVE_VALIDATION_STATES + ("superseded",)

# Governance statuses set by forget/reject cascades. They leave validation_state
# untouched, so read paths must exclude them by `status` regardless of
# validation_state, or forgotten data leaks back into retrieval.
RETRIEVAL_EXCLUDED_STATUSES: tuple[str, ...] = (
    "archived",
    "invalidated",
    "user_rejected",
    "shadow",
)


@dataclass(frozen=True)
class _ValidationThresholds:
    stable_count: int
    stable_span_hours: float
    corroborated_count: int

    @classmethod
    def from_config(cls) -> "_ValidationThresholds":
        return cls(
            stable_count=assertion_int_setting(
                "stable_evidence_count",
                STABLE_EVIDENCE_COUNT,
            ),
            stable_span_hours=assertion_float_setting(
                "stable_time_span_hours",
                STABLE_TIME_SPAN_HOURS,
            ),
            corroborated_count=assertion_int_setting(
                "corroborated_evidence_count",
                CORROBORATED_EVIDENCE_COUNT,
            ),
        )


def compute_confidence(evidence_count: int) -> float:
    """Base confidence curve from accumulated evidence count."""
    base = assertion_float_setting("confidence_base", CONFIDENCE_BASE)
    slope = assertion_float_setting("confidence_slope", CONFIDENCE_SLOPE)
    ceiling = assertion_float_setting("confidence_ceiling", CONFIDENCE_CEILING)
    return min(ceiling, base + slope * max(0, evidence_count - 1))


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

    feedback_result = _state_from_user_feedback(
        user_feedback,
        current_confidence=current_confidence,
        is_temporary=is_temporary,
    )
    if feedback_result is not None:
        return feedback_result

    terminal_result = _state_from_terminal_current_state(
        current_state,
        current_confidence=current_confidence,
    )
    if terminal_result is not None:
        return terminal_result

    thresholds = _ValidationThresholds.from_config()
    if is_temporary:
        temporary_result = _state_for_temporary_trait(
            current_confidence=current_confidence,
            evidence_count=evidence_count,
            time_span_hours=time_span_hours,
            thresholds=thresholds,
        )
        if temporary_result is not None:
            return temporary_result

    return _state_for_general_trait(
        current_confidence=current_confidence,
        evidence_count=evidence_count,
        time_span_hours=time_span_hours,
        thresholds=thresholds,
    )


def _state_from_user_feedback(
    user_feedback: Optional[str],
    *,
    current_confidence: float,
    is_temporary: bool,
) -> tuple[str, float, str] | None:
    if user_feedback == "rejected":
        return (
            "user_rejected",
            assertion_float_setting("user_rejected_confidence", USER_REJECTED_CONFIDENCE),
            "volatile_pattern",
        )

    if user_feedback == "confirmed":
        stability_kind = "temporary_state" if is_temporary else "stable_trait"
        return (
            "stable",
            max(
                current_confidence,
                assertion_float_setting(
                    "user_confirmed_confidence_floor",
                    USER_CONFIRMED_CONFIDENCE_FLOOR,
                ),
            ),
            stability_kind,
        )
    return None


def _state_from_terminal_current_state(
    current_state: str,
    *,
    current_confidence: float,
) -> tuple[str, float, str] | None:
    if current_state == "user_rejected":
        return (
            "user_rejected",
            min(
                current_confidence,
                assertion_float_setting("user_rejected_confidence", USER_REJECTED_CONFIDENCE),
            ),
            "volatile_pattern",
        )

    if current_state == "expired":
        return (
            "expired",
            min(
                current_confidence,
                assertion_float_setting("expired_confidence_ceiling", EXPIRED_CONFIDENCE_CEILING),
            ),
            "volatile_pattern",
        )

    if current_state == "contradicted":
        return (
            "contradicted",
            min(
                current_confidence,
                assertion_float_setting(
                    "contradicted_confidence_ceiling",
                    CONTRADICTED_CONFIDENCE_CEILING,
                ),
            ),
            "volatile_pattern",
        )
    return None


def _state_for_temporary_trait(
    *,
    current_confidence: float,
    evidence_count: int,
    time_span_hours: float,
    thresholds: _ValidationThresholds,
) -> tuple[str, float, str] | None:
    if (
        evidence_count >= thresholds.stable_count
        and time_span_hours >= thresholds.stable_span_hours
    ):
        return (
            "stable",
            max(
                current_confidence,
                assertion_float_setting("stable_confidence_floor", STABLE_CONFIDENCE_FLOOR),
            ),
            "temporary_state",
        )
    if evidence_count >= 1:
        return (
            "corroborated",
            max(
                current_confidence,
                assertion_float_setting(
                    "temporary_corroborated_confidence_floor",
                    TEMPORARY_CORROBORATED_CONFIDENCE_FLOOR,
                ),
            ),
            "temporary_state",
        )
    return None


def _state_for_general_trait(
    *,
    current_confidence: float,
    evidence_count: int,
    time_span_hours: float,
    thresholds: _ValidationThresholds,
) -> tuple[str, float, str]:
    if (
        evidence_count >= thresholds.stable_count
        and time_span_hours >= thresholds.stable_span_hours
    ):
        return (
            "stable",
            max(
                current_confidence,
                assertion_float_setting("stable_confidence_floor", STABLE_CONFIDENCE_FLOOR),
            ),
            "stable_trait",
        )

    if evidence_count >= thresholds.corroborated_count:
        return (
            "corroborated",
            max(
                current_confidence,
                assertion_float_setting(
                    "corroborated_confidence_floor",
                    CORROBORATED_CONFIDENCE_FLOOR,
                ),
            ),
            "volatile_pattern",
        )

    return (
        "tentative",
        min(
            current_confidence,
            assertion_float_setting("tentative_confidence_ceiling", TENTATIVE_CONFIDENCE_CEILING),
        ),
        "volatile_pattern",
    )


__all__ = [
    "compute_confidence",
    "derive_validation_state",
    "CONFIDENCE_BASE",
    "CONFIDENCE_SLOPE",
    "CONFIDENCE_CEILING",
    "STABLE_EVIDENCE_COUNT",
    "STABLE_TIME_SPAN_HOURS",
    "CORROBORATED_EVIDENCE_COUNT",
    "USER_REJECTED_CONFIDENCE",
    "USER_CONFIRMED_CONFIDENCE_FLOOR",
    "EXPIRED_CONFIDENCE_CEILING",
    "CONTRADICTED_CONFIDENCE_CEILING",
    "STABLE_CONFIDENCE_FLOOR",
    "TEMPORARY_CORROBORATED_CONFIDENCE_FLOOR",
    "CORROBORATED_CONFIDENCE_FLOOR",
    "TENTATIVE_CONFIDENCE_CEILING",
    "_TEMPORARY_STATE_TRAITS",
    "ACTIVE_VALIDATION_STATES",
    "HISTORICAL_VALIDATION_STATES",
    "RETRIEVAL_EXCLUDED_STATUSES",
]
