"""Deterministic horizon promotion for L2 assertion candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..phase1_models import L2TemporalCue

_EVENT_ONLY_TTL_SECONDS = 24 * 60 * 60
_RECENT_TTL_SECONDS = 14 * 24 * 60 * 60
_PROJECT_RECENT_TTL_SECONDS = 30 * 24 * 60 * 60
_RECENT_MIN_OBSERVATIONS = 3
_RECENT_MIN_EVIDENCE = 2
_RECENT_MIN_DISTINCT_DAYS = 2
_DURABLE_MIN_OBSERVATIONS = 6
_DURABLE_MIN_EVIDENCE = 4
_DURABLE_MIN_DISTINCT_DAYS = 3
_DURABLE_MIN_SPAN_DAYS = 14.0
_DURABLE_MAX_AGE_DAYS = 30.0
_SUSTAINED_RECENT_MIN_OBSERVATIONS = 2
_SUSTAINED_RECENT_MIN_EVIDENCE = 2
_SUSTAINED_RECENT_MIN_DISTINCT_DAYS = 2

_SHORT_LIVED_FAMILIES = frozenset(
    {
        "engagement",
        "group_atmosphere",
        "mood",
        "public_sentiment",
        "relationship_shift",
        "stress",
    }
)
_EXPLICIT_PROFILE_PREDICATES = frozenset(
    {
        "BIRTH_DATE",
        "BIRTH_YEAR",
        "DISALLOWED_FORM_OF_ADDRESS",
        "PREFERRED_COMMUNICATION_STYLE",
        "PREFERRED_FORM_OF_ADDRESS",
        "REAL_NAME",
        "STATED_AGE",
    }
)
_PREFERENCE_PREDICATES = frozenset({"DISLIKES", "LIKES"})


class PromotionHorizon(str, Enum):
    """Host-owned retention horizon for one assertion candidate."""

    EVENT_ONLY = "event_only"
    RECENT = "recent"
    DURABLE = "durable"


class SourceStrengthPreset(str, Enum):
    """Evidence-source presets used by explicit promotion gates."""

    AUTO = "auto"
    DIRECT_USER = "direct_user"
    STRUCTURED_SOURCE = "structured_source"
    PASSIVE_EXPOSURE = "passive_exposure"
    SUSTAINED_ENGAGEMENT = "sustained_engagement"
    DELIBERATE_CHOICE = "deliberate_choice"

    @classmethod
    def from_value(cls, value: "SourceStrengthPreset | str") -> "SourceStrengthPreset":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().casefold() or cls.AUTO.value
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(f"Unsupported source strength preset: {value}") from exc


@dataclass(frozen=True, slots=True)
class ExpiryGuidance:
    """Persistence guidance derived from a promotion decision."""

    temporal_scope: str
    decay_policy: str
    ttl_seconds: float | None


@dataclass(frozen=True, slots=True)
class AssertionPromotionInput:
    """Grounded evidence statistics consumed by the promotion evaluator."""

    fact_kind: str
    predicate: str
    evidence_class: str
    temporal_cue: L2TemporalCue | str
    trait_family: str = ""
    source_strength: SourceStrengthPreset | str = SourceStrengthPreset.AUTO
    observation_count: int = 1
    evidence_count: int = 1
    distinct_days: int = 1
    span_days: float = 0.0
    recency_days: float | None = 0.0
    user_feedback: str | None = None
    durable_permitted: bool = True
    baseline_temporal_scope: str | None = None
    baseline_decay_policy: str | None = None
    baseline_ttl_seconds: float | None = None
    recent_min_observations: int = _RECENT_MIN_OBSERVATIONS
    recent_min_evidence: int = _RECENT_MIN_EVIDENCE
    recent_min_distinct_days: int = _RECENT_MIN_DISTINCT_DAYS
    recent_max_age_days: float | None = None
    durable_min_observations: int = _DURABLE_MIN_OBSERVATIONS
    durable_min_evidence: int = _DURABLE_MIN_EVIDENCE
    durable_min_distinct_days: int = _DURABLE_MIN_DISTINCT_DAYS
    durable_min_span_days: float = _DURABLE_MIN_SPAN_DAYS
    durable_max_age_days: float = _DURABLE_MAX_AGE_DAYS

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_kind", _normalized_text(self.fact_kind))
        object.__setattr__(self, "predicate", str(self.predicate or "").strip().upper())
        object.__setattr__(self, "evidence_class", _normalized_text(self.evidence_class))
        object.__setattr__(self, "trait_family", _normalized_text(self.trait_family))
        object.__setattr__(
            self,
            "source_strength",
            SourceStrengthPreset.from_value(self.source_strength),
        )
        object.__setattr__(self, "temporal_cue", L2TemporalCue.from_value(self.temporal_cue))
        object.__setattr__(self, "observation_count", max(0, int(self.observation_count or 0)))
        object.__setattr__(self, "evidence_count", max(0, int(self.evidence_count or 0)))
        object.__setattr__(self, "distinct_days", max(0, int(self.distinct_days or 0)))
        object.__setattr__(self, "span_days", max(0.0, float(self.span_days or 0.0)))
        object.__setattr__(
            self,
            "recency_days",
            None if self.recency_days is None else max(0.0, float(self.recency_days)),
        )
        object.__setattr__(self, "user_feedback", _normalized_text(self.user_feedback))
        object.__setattr__(self, "durable_permitted", bool(self.durable_permitted))
        object.__setattr__(
            self,
            "recent_min_observations",
            max(1, int(self.recent_min_observations or 1)),
        )
        object.__setattr__(
            self,
            "recent_min_evidence",
            max(1, int(self.recent_min_evidence or 1)),
        )
        object.__setattr__(
            self,
            "recent_min_distinct_days",
            max(1, int(self.recent_min_distinct_days or 1)),
        )
        object.__setattr__(
            self,
            "recent_max_age_days",
            (
                None
                if self.recent_max_age_days is None
                else max(0.0, float(self.recent_max_age_days))
            ),
        )
        object.__setattr__(
            self,
            "durable_min_observations",
            max(1, int(self.durable_min_observations or 1)),
        )
        object.__setattr__(
            self,
            "durable_min_evidence",
            max(1, int(self.durable_min_evidence or 1)),
        )
        object.__setattr__(
            self,
            "durable_min_distinct_days",
            max(1, int(self.durable_min_distinct_days or 1)),
        )
        object.__setattr__(
            self,
            "durable_min_span_days",
            max(0.0, float(self.durable_min_span_days or 0.0)),
        )
        object.__setattr__(
            self,
            "durable_max_age_days",
            max(0.0, float(self.durable_max_age_days or 0.0)),
        )


@dataclass(frozen=True, slots=True)
class AssertionPromotionDecision:
    """Explicit promotion outcome with persistence guidance and reason code."""

    horizon: PromotionHorizon
    expiry: ExpiryGuidance
    reason: str


def evaluate_assertion_promotion(
    evidence: AssertionPromotionInput,
) -> AssertionPromotionDecision:
    """Evaluate grounded evidence with ordered, inspectable promotion gates."""

    if evidence.user_feedback in {"rejected", "user_rejected"}:
        return _event_only("user_rejected")

    if evidence.trait_family in _SHORT_LIVED_FAMILIES:
        return _recent(
            "short_lived_state",
            trait_family=evidence.trait_family,
            temporal_scope=evidence.baseline_temporal_scope,
            decay_policy=evidence.baseline_decay_policy,
            ttl_seconds=evidence.baseline_ttl_seconds,
        )

    if evidence.fact_kind == "future_intent":
        if (
            evidence.trait_family == "goal_profile"
            and evidence.predicate == "PLANS_TO"
            and _resolved_source_strength(evidence) is SourceStrengthPreset.DIRECT_USER
        ):
            return _recent(
                "direct_goal_intent",
                trait_family=evidence.trait_family,
                temporal_scope=evidence.baseline_temporal_scope,
                decay_policy=evidence.baseline_decay_policy,
                ttl_seconds=evidence.baseline_ttl_seconds,
            )
        return _event_only("unsupported_future_intent")

    if evidence.fact_kind == "public_topology":
        return _event_only("non_profile_fact_kind")

    if evidence.temporal_cue is L2TemporalCue.ONE_OFF:
        return _event_only("explicit_one_off")

    strength = _resolved_source_strength(evidence)
    if strength is SourceStrengthPreset.DELIBERATE_CHOICE:
        if evidence.durable_permitted:
            return _durable("deliberate_choice_durable")
        return _recent(
            "deliberate_choice_recent",
            trait_family=evidence.trait_family,
        )
    if strength is SourceStrengthPreset.PASSIVE_EXPOSURE:
        if _passes_recent_accumulation_gates(evidence):
            return _recent(
                "passive_exposure_accumulated",
                trait_family=evidence.trait_family,
            )
        return _event_only("passive_exposure_below_recent_gates")

    if evidence.temporal_cue is L2TemporalCue.RECENT:
        return _recent("explicit_recent", trait_family=evidence.trait_family)

    if evidence.durable_permitted and _is_explicit_durable_fact(evidence, strength):
        return _durable("explicit_durable_fact")

    if strength in {
        SourceStrengthPreset.SUSTAINED_ENGAGEMENT,
        SourceStrengthPreset.STRUCTURED_SOURCE,
    }:
        if _passes_durable_engagement_gates(evidence) and evidence.durable_permitted:
            return _durable("sustained_engagement_durable_gates")
        if _passes_recent_accumulation_gates(evidence):
            return _recent(
                "sustained_engagement_recent_gates",
                trait_family=evidence.trait_family,
            )
        return _event_only("sustained_engagement_below_recent_gates")

    if (
        strength is SourceStrengthPreset.DIRECT_USER
        and evidence.durable_permitted
        and evidence.temporal_cue is L2TemporalCue.STABLE
    ):
        return _durable("explicit_stable_wording")

    if _passes_recent_accumulation_gates(evidence):
        return _recent(
            "accumulated_recent_evidence",
            trait_family=evidence.trait_family,
        )

    return _event_only("insufficient_promotion_evidence")


def _resolved_source_strength(evidence: AssertionPromotionInput) -> SourceStrengthPreset:
    source_strength = SourceStrengthPreset.from_value(evidence.source_strength)
    if source_strength is not SourceStrengthPreset.AUTO:
        return source_strength
    if evidence.evidence_class == "user_self_report":
        return SourceStrengthPreset.DIRECT_USER
    if evidence.fact_kind == "interaction_evidence":
        return SourceStrengthPreset.PASSIVE_EXPOSURE
    return SourceStrengthPreset.STRUCTURED_SOURCE


def _is_explicit_durable_fact(
    evidence: AssertionPromotionInput,
    strength: SourceStrengthPreset,
) -> bool:
    if strength not in {
        SourceStrengthPreset.DIRECT_USER,
        SourceStrengthPreset.STRUCTURED_SOURCE,
    }:
        return False
    if evidence.predicate in _EXPLICIT_PROFILE_PREDICATES:
        return True
    if (
        strength is SourceStrengthPreset.DIRECT_USER
        and evidence.trait_family == "interest_profile"
        and evidence.predicate == "INTERESTED_IN"
    ):
        return True
    return (
        evidence.fact_kind == "stable_preference"
        and evidence.predicate in _PREFERENCE_PREDICATES
    )


def _passes_recent_accumulation_gates(evidence: AssertionPromotionInput) -> bool:
    strength = _resolved_source_strength(evidence)
    if strength is SourceStrengthPreset.PASSIVE_EXPOSURE:
        floor_observations = _RECENT_MIN_OBSERVATIONS
        floor_evidence = _RECENT_MIN_EVIDENCE
        floor_distinct_days = _RECENT_MIN_DISTINCT_DAYS
    elif strength is SourceStrengthPreset.SUSTAINED_ENGAGEMENT:
        floor_observations = _SUSTAINED_RECENT_MIN_OBSERVATIONS
        floor_evidence = _SUSTAINED_RECENT_MIN_EVIDENCE
        floor_distinct_days = _SUSTAINED_RECENT_MIN_DISTINCT_DAYS
    else:
        floor_observations = 1
        floor_evidence = 1
        floor_distinct_days = 1
    return bool(
        evidence.observation_count
        >= max(evidence.recent_min_observations, floor_observations)
        and evidence.evidence_count >= max(evidence.recent_min_evidence, floor_evidence)
        and evidence.distinct_days
        >= max(evidence.recent_min_distinct_days, floor_distinct_days)
        and _is_recent_enough(
            evidence.recency_days,
            max_age_days=_recent_max_age_days(evidence),
        )
    )


def _passes_durable_engagement_gates(evidence: AssertionPromotionInput) -> bool:
    return bool(
        evidence.observation_count
        >= max(evidence.durable_min_observations, _DURABLE_MIN_OBSERVATIONS)
        and evidence.evidence_count
        >= max(evidence.durable_min_evidence, _DURABLE_MIN_EVIDENCE)
        and evidence.distinct_days
        >= max(evidence.durable_min_distinct_days, _DURABLE_MIN_DISTINCT_DAYS)
        and evidence.span_days
        >= max(evidence.durable_min_span_days, _DURABLE_MIN_SPAN_DAYS)
        and _is_recent_enough(
            evidence.recency_days,
            max_age_days=evidence.durable_max_age_days,
        )
    )


def _recent_max_age_days(evidence: AssertionPromotionInput) -> float:
    if evidence.recent_max_age_days is not None:
        return evidence.recent_max_age_days
    if evidence.trait_family == "project_profile":
        return float(_PROJECT_RECENT_TTL_SECONDS / 86_400)
    return float(_RECENT_TTL_SECONDS / 86_400)


def _is_recent_enough(recency_days: float | None, *, max_age_days: float) -> bool:
    return recency_days is not None and recency_days <= max_age_days


def _event_only(reason: str) -> AssertionPromotionDecision:
    return AssertionPromotionDecision(
        horizon=PromotionHorizon.EVENT_ONLY,
        expiry=ExpiryGuidance(
            temporal_scope="momentary",
            decay_policy="fast_decay",
            ttl_seconds=float(_EVENT_ONLY_TTL_SECONDS),
        ),
        reason=reason,
    )


def _recent(
    reason: str,
    *,
    trait_family: str = "",
    temporal_scope: str | None = None,
    decay_policy: str | None = None,
    ttl_seconds: float | None = None,
) -> AssertionPromotionDecision:
    default_ttl = (
        _PROJECT_RECENT_TTL_SECONDS
        if str(trait_family or "").strip().casefold() == "project_profile"
        else _RECENT_TTL_SECONDS
    )
    return AssertionPromotionDecision(
        horizon=PromotionHorizon.RECENT,
        expiry=ExpiryGuidance(
            temporal_scope=str(temporal_scope or "recent"),
            decay_policy=str(decay_policy or "time_window"),
            ttl_seconds=float(ttl_seconds) if ttl_seconds is not None else default_ttl,
        ),
        reason=reason,
    )


def _durable(reason: str) -> AssertionPromotionDecision:
    return AssertionPromotionDecision(
        horizon=PromotionHorizon.DURABLE,
        expiry=ExpiryGuidance(
            temporal_scope="stable",
            decay_policy="evidence_only",
            ttl_seconds=None,
        ),
        reason=reason,
    )


def _normalized_text(value: object) -> str:
    return str(value or "").strip().casefold()


__all__ = [
    "AssertionPromotionDecision",
    "AssertionPromotionInput",
    "ExpiryGuidance",
    "PromotionHorizon",
    "SourceStrengthPreset",
    "evaluate_assertion_promotion",
]
