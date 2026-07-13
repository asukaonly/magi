"""Assertion reconcile state and trait classification helpers."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..assertion_family_policy import get_assertion_family_policy
from ..storage.utils import MOMENTARY_TRAITS as _MOMENTARY_TRAITS
from .settings import (
    CONTRADICTED_CONFIDENCE_CEILING,
    USER_REJECTED_CONFIDENCE,
    assertion_float_setting,
    momentary_ttl_seconds,
)
from .state_machine import (
    _TEMPORARY_STATE_TRAITS,
    derive_validation_state as _derive_validation_state,
)


class L2ReconcileStateMixin:
    """Derive assertion state, snapshot targets, and confidence adjustments."""

    def _derive_trait_family(self, trait_name: str) -> str:
        normalized = trait_name.strip().lower()
        if normalized == "stress_level":
            return "stress"
        if normalized in {"mood", "annoyance", "irritation", "frustration"}:
            return "mood"
        if normalized == "engagement":
            return "engagement"
        if normalized.startswith("trigger."):
            return "trigger"
        if normalized == "taste_preference":
            return "preference_profile"
        if normalized.startswith("identity."):
            return "identity_profile"
        if normalized.startswith("communication."):
            return "communication_profile"
        if normalized.startswith("preference."):
            return "preference_profile"
        if normalized.startswith("interest."):
            return "interest_profile"
        if normalized.startswith("project."):
            return "project_profile"
        if normalized.startswith("routine."):
            return "routine_profile"
        if normalized.startswith("state."):
            return "state_profile"
        return "preference_profile"

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_expires_at(
        self,
        value: Any,
        *,
        trait_family: str,
        trait_name: str,
        target_entity_id: str,
        anchor_at: float,
    ) -> float | None:
        if value is not None:
            return float(value)
        normalized_trait_name = trait_name.strip().lower()
        if target_entity_id and normalized_trait_name in _MOMENTARY_TRAITS:
            return anchor_at + momentary_ttl_seconds()
        policy = get_assertion_family_policy(trait_family)
        if policy is not None and policy.default_ttl_seconds is not None:
            return anchor_at + policy.default_ttl_seconds
        return None

    def _is_assertion_expired(self, assertion: Dict[str, Any], *, now: float | None = None) -> bool:
        expires_at = assertion.get("expires_at")
        if expires_at is None:
            return False
        current_time = float(now if now is not None else time.time())
        return float(expires_at) <= current_time

    _TEMPORARY_STATE_TRAITS = _TEMPORARY_STATE_TRAITS

    def _derive_reconcile_state(
        self,
        *,
        current_state: str,
        current_confidence: float,
        evidence_count: int,
        time_span_hours: float,
        trait_name: str,
        user_feedback: Optional[str] = None,
    ) -> tuple[str, float, str]:
        return _derive_validation_state(
            current_state=current_state,
            current_confidence=current_confidence,
            evidence_count=evidence_count,
            time_span_hours=time_span_hours,
            trait_name=trait_name,
            user_feedback=user_feedback,
        )

    def _recommend_snapshot_field(self, *, trait_name: str, status: str) -> str:
        if status not in {"stable", "corroborated"}:
            return "none"
        if trait_name.startswith(("preference.", "interest.")):
            return "preferences"
        if trait_name.startswith("trigger."):
            return "sensitive_triggers"
        if trait_name == "stress_level":
            return "core_traits" if status == "stable" else "current_stress_level"
        if trait_name == "mood":
            return "current_mood"
        if trait_name == "engagement":
            return "current_engagement"
        return "core_traits"

    def _engagement_value(self, value: str) -> float:
        normalized = value.strip().lower()
        if normalized in {"high", "engaged", "focused"}:
            return 0.9
        if normalized in {"low", "disengaged", "distant"}:
            return 0.2
        try:
            return float(normalized)
        except ValueError:
            return 0.5

    def _contradicted_confidence(self, *, current_confidence: float, hint_confidence: float, action: str) -> float:
        ceiling = assertion_float_setting(
            "contradicted_confidence_ceiling",
            CONTRADICTED_CONFIDENCE_CEILING,
        )
        floor = min(
            ceiling,
            assertion_float_setting("user_rejected_confidence", USER_REJECTED_CONFIDENCE),
        )
        base = current_confidence * ceiling
        if action == "mark_conflicted":
            return round(max(floor, min(base, ceiling)), 4)
        if action == "revalidate_only":
            return round(max(0.15, current_confidence * 0.75), 4)
        confidence_weight = 1.0 - min(max(hint_confidence, 0.0), 1.0) * 0.45
        return round(max(floor, min(current_confidence * confidence_weight, ceiling)), 4)


__all__ = ["L2ReconcileStateMixin", "_MOMENTARY_TRAITS"]
