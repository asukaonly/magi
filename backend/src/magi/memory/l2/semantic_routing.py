"""Host-owned semantic routing for immutable grounded Claims."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from ...utils.calendar_timezone import canonical_timezone_id
from .claims.identity import canonical_json
from .ontology import PROFILE_SIGNAL_PREDICATES
from .predicate_catalog import SPEC_BY_CANONICAL

ROUTE_CONTRACT_VERSION = 5
SLOT_SCHEMA_VERSION = 2


class ObjectRole(str, Enum):
    """Meaning assigned to the Claim object by one route contract."""

    CANONICAL_VALUE = "canonical_value"
    TARGET_IDENTITY = "target_identity"
    TARGET_ID_OR_TEXT = "target_id_or_text"
    GOAL_TEXT = "goal_text"
    STRUCTURED_TARGET_AND_VALUE = "structured_target_and_value"
    UNSUPPORTED = "unsupported"


class ProjectionTarget(str, Enum):
    """Product projection explicitly supported by one semantic route."""

    GRAPH = "graph"
    ASSERTION = "assertion"


class RouteDisposition(str, Enum):
    """Exhaustive host decision for assertion projection eligibility."""

    ROUTED = "routed"
    NOT_APPLICABLE = "not_applicable"
    DEFERRED = "deferred"
    UNROUTED = "unrouted"


@dataclass(frozen=True, slots=True)
class SemanticRouteInput:
    """Minimum immutable Claim material consumed by the router."""

    claim_id: str
    subject_id: str
    subject_type: str
    canonical_predicate: str
    fact_kind: str
    object_type: str
    object_value: Any | None
    object_entity_id: str | None
    temporal_cue: str
    specificity: str
    target_from: float | None
    target_to: float | None
    raw_time_expression: str
    time_resolution: str
    time_frame: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SemanticRouteDecision:
    """Deterministic route result with value-independent identity."""

    claim_id: str
    disposition: RouteDisposition
    reason_code: str
    semantic_route_id: str | None = None
    route_key: str | None = None
    slot_key: str | None = None
    family: str | None = None
    trait_code: str | None = None
    object_role: ObjectRole = ObjectRole.UNSUPPORTED
    canonical_value: Any | None = None
    value_fingerprint: str | None = None
    subject_id: str | None = None
    subject_type: str | None = None
    target_entity_id: str | None = None
    target_entity_type: str | None = None
    object_surface: str | None = None
    normalized_target_text: str | None = None
    semantic_target_key: str | None = None
    goal_lineage_key: str | None = None
    target_window_key: str | None = None
    projection_targets: frozenset[ProjectionTarget] = frozenset()
    scope_key: str = "global"

    @property
    def can_project_assertion(self) -> bool:
        return (
            self.disposition is RouteDisposition.ROUTED
            and ProjectionTarget.ASSERTION in self.projection_targets
            and bool(self.slot_key)
        )

    @property
    def can_project_graph(self) -> bool:
        return (
            ProjectionTarget.GRAPH in self.projection_targets
            and bool(self.target_entity_id)
        )


@dataclass(frozen=True, slots=True)
class _RouteSpec:
    semantic_route_id: str
    family: str
    trait_code: str
    object_role: ObjectRole
    allowed_fact_kinds: frozenset[str]
    projection_targets: frozenset[ProjectionTarget]
    canonical_value: str | None = None
    required_object_type: str | None = None


_ASSERTION_ONLY = frozenset({ProjectionTarget.ASSERTION})
_GRAPH_AND_ASSERTION = frozenset(
    {ProjectionTarget.GRAPH, ProjectionTarget.ASSERTION}
)
_GRAPH_ONLY = frozenset({ProjectionTarget.GRAPH})


_STATED_AGE_SPEC = _RouteSpec(
    "identity.age.stated",
    "identity_profile",
    "identity.age.stated",
    ObjectRole.CANONICAL_VALUE,
    frozenset({"explicit_fact"}),
    _ASSERTION_ONLY,
)

_ASCII_INTEGER = re.compile(r"[0-9]+")


_LITERAL_SPECS: dict[str, _RouteSpec] = {
    "REAL_NAME": _RouteSpec(
        "identity.real_name",
        "identity_profile",
        "identity.real_name",
        ObjectRole.CANONICAL_VALUE,
        frozenset({"explicit_fact"}),
        _ASSERTION_ONLY,
    ),
    "BIRTH_DATE": _RouteSpec(
        "identity.birth_date",
        "identity_profile",
        "identity.birth_date",
        ObjectRole.CANONICAL_VALUE,
        frozenset({"explicit_fact"}),
        _ASSERTION_ONLY,
    ),
    "BIRTH_YEAR": _RouteSpec(
        "identity.birth_year",
        "identity_profile",
        "identity.birth_year",
        ObjectRole.CANONICAL_VALUE,
        frozenset({"explicit_fact"}),
        _ASSERTION_ONLY,
    ),
    "STATED_AGE": _STATED_AGE_SPEC,
    # AGE is retained as a declared profile signal. Canonicalization normally
    # rewrites it to STATED_AGE before routing, but the router remains closed
    # and deterministic when handed an already-persisted AGE Claim.
    "AGE": _STATED_AGE_SPEC,
    "PREFERRED_FORM_OF_ADDRESS": _RouteSpec(
        "communication.address.preferred",
        "communication_profile",
        "communication.address.preferred",
        ObjectRole.CANONICAL_VALUE,
        frozenset({"explicit_fact"}),
        _ASSERTION_ONLY,
    ),
    "DISALLOWED_FORM_OF_ADDRESS": _RouteSpec(
        "communication.address.disallowed",
        "communication_profile",
        "communication.address.disallowed",
        ObjectRole.CANONICAL_VALUE,
        frozenset({"explicit_fact"}),
        _ASSERTION_ONLY,
    ),
    "PREFERRED_COMMUNICATION_STYLE": _RouteSpec(
        "communication.response_style.preferred",
        "communication_profile",
        "communication.response_style.preferred",
        ObjectRole.CANONICAL_VALUE,
        frozenset({"explicit_fact"}),
        _ASSERTION_ONLY,
    ),
}

_TARGET_SPECS: dict[str, _RouteSpec] = {
    "LIKES": _RouteSpec(
        "preference.affinity",
        "preference_profile",
        "preference.affinity",
        ObjectRole.TARGET_ID_OR_TEXT,
        frozenset({"explicit_fact", "stable_preference"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="like",
    ),
    "DISLIKES": _RouteSpec(
        "preference.affinity",
        "preference_profile",
        "preference.affinity",
        ObjectRole.TARGET_ID_OR_TEXT,
        frozenset({"explicit_fact", "stable_preference"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="dislike",
    ),
    "INTERESTED_IN": _RouteSpec(
        "interest.attention",
        "interest_profile",
        "interest.attention",
        ObjectRole.TARGET_ID_OR_TEXT,
        frozenset({"explicit_fact"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="interested",
    ),
    "CREATES": _RouteSpec(
        "project.role.creator",
        "project_profile",
        "project.role.creator",
        ObjectRole.TARGET_IDENTITY,
        frozenset({"explicit_fact"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="creator",
        required_object_type="project",
    ),
    "WORKS_ON": _RouteSpec(
        "project.engagement.active",
        "project_profile",
        "project.engagement.active",
        ObjectRole.TARGET_IDENTITY,
        frozenset({"explicit_fact"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="active",
        required_object_type="project",
    ),
    "DEVELOPS": _RouteSpec(
        "project.role.developer",
        "project_profile",
        "project.role.developer",
        ObjectRole.TARGET_IDENTITY,
        frozenset({"explicit_fact"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="developer",
        required_object_type="project",
    ),
    "MAINTAINS": _RouteSpec(
        "project.role.maintainer",
        "project_profile",
        "project.role.maintainer",
        ObjectRole.TARGET_IDENTITY,
        frozenset({"explicit_fact"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="maintainer",
        required_object_type="project",
    ),
    "CONTRIBUTES_TO": _RouteSpec(
        "project.role.contributor",
        "project_profile",
        "project.role.contributor",
        ObjectRole.TARGET_IDENTITY,
        frozenset({"explicit_fact"}),
        _GRAPH_AND_ASSERTION,
        canonical_value="contributor",
        required_object_type="project",
    ),
}

_FEELS_SPEC = _RouteSpec(
    "state.mood.current",
    "mood",
    "mood",
    ObjectRole.CANONICAL_VALUE,
    frozenset({"explicit_fact"}),
    _ASSERTION_ONLY,
)

_GOAL_SPEC = _RouteSpec(
    "goal.intent",
    "goal_profile",
    "goal.intent",
    ObjectRole.GOAL_TEXT,
    frozenset({"future_intent"}),
    _ASSERTION_ONLY,
    canonical_value="planned",
)

ROUTE_EXTENSION_PREDICATES = frozenset(
    {"CONTRIBUTES_TO", "DEVELOPS", "FEELS", "MAINTAINS", "WORKS_ON"}
)

_DERIVED_RULE_PREDICATES = frozenset(
    {
        "ATTENDED",
        "CHECKED_OUT",
        "COMMITTED",
        "EXECUTED",
        "FOLLOWS",
        "LISTENED",
        "MERGED",
        "REBASED",
        "USED",
        "USES",
        "VIEWED",
        "VISITED",
    }
)

_RELATIONSHIP_ONLY_PREDICATES = frozenset(
    {
        "FAMILY_OF",
        "INTERACTED_WITH",
        "KNOWS",
        "LIVES_IN",
        "LOCATED_IN",
        "MEMBER_OF",
        "ON_PLATFORM",
        "OWNS",
        "PRESENCE_OF",
        "PROFICIENT_IN",
        "REFERENCES",
        "WORKS_AT",
        "WORKS_WITH",
    }
)


_ROUTE_DISPOSITION_BY_PREDICATE: dict[str, RouteDisposition] = {
    **dict.fromkeys(_LITERAL_SPECS, RouteDisposition.ROUTED),
    **dict.fromkeys(_TARGET_SPECS, RouteDisposition.ROUTED),
    **dict.fromkeys(_DERIVED_RULE_PREDICATES, RouteDisposition.DEFERRED),
    **dict.fromkeys(
        _RELATIONSHIP_ONLY_PREDICATES,
        RouteDisposition.NOT_APPLICABLE,
    ),
    "FEELS": RouteDisposition.ROUTED,
    "HAS_METRIC": RouteDisposition.UNROUTED,
    "PLANS_TO": RouteDisposition.ROUTED,
}

# Public, immutable coverage table. Adding a catalog predicate or profile
# signal requires choosing a disposition instead of silently falling through.
ROUTE_DISPOSITION_BY_PREDICATE: Mapping[str, RouteDisposition] = MappingProxyType(
    dict(_ROUTE_DISPOSITION_BY_PREDICATE)
)


def _validate_route_disposition_table() -> None:
    groups = (
        set(_LITERAL_SPECS),
        set(_TARGET_SPECS),
        set(_DERIVED_RULE_PREDICATES),
        set(_RELATIONSHIP_ONLY_PREDICATES),
        {"FEELS", "HAS_METRIC", "PLANS_TO"},
    )
    seen: set[str] = set()
    duplicates: set[str] = set()
    for group in groups:
        duplicates.update(seen.intersection(group))
        seen.update(group)

    expected = (
        set(SPEC_BY_CANONICAL).union(PROFILE_SIGNAL_PREDICATES).union(ROUTE_EXTENSION_PREDICATES)
    )
    declared = set(ROUTE_DISPOSITION_BY_PREDICATE)
    missing = expected.difference(declared)
    extra = declared.difference(expected)
    if duplicates or missing or extra:
        raise RuntimeError(
            "semantic route disposition table is inconsistent: "
            f"duplicates={sorted(duplicates)}, "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )


_validate_route_disposition_table()

_BIRTH_DATE = re.compile(
    r"^(?:(?P<year>[0-9]{4})-)?" r"(?P<month>0[1-9]|1[0-2])-(?P<day>0[1-9]|[12][0-9]|3[01])$"
)


def derive_semantic_route(route_input: SemanticRouteInput) -> SemanticRouteDecision:
    """Return one exhaustive route decision without consulting model output."""

    _required(route_input.claim_id)
    _required(route_input.subject_id)
    _required(route_input.subject_type)
    predicate = _required(route_input.canonical_predicate).upper()
    fact_kind = _required(route_input.fact_kind).casefold()
    object_type = _required(route_input.object_type).casefold()

    if predicate == "PLANS_TO":
        if fact_kind not in _GOAL_SPEC.allowed_fact_kinds:
            return _mismatch(route_input, _GOAL_SPEC)
        if str(route_input.specificity or "").strip().casefold() != "concrete":
            return _non_routed(
                route_input,
                disposition=RouteDisposition.UNROUTED,
                reason_code="goal_target_not_concrete",
                object_role=_GOAL_SPEC.object_role,
                projection_targets=_GOAL_SPEC.projection_targets,
            )
        goal_text = _normalize_semantic_text(route_input.object_value)
        if not goal_text:
            return _non_routed(
                route_input,
                disposition=RouteDisposition.UNROUTED,
                reason_code="invalid_goal_text",
                object_role=_GOAL_SPEC.object_role,
                projection_targets=_GOAL_SPEC.projection_targets,
            )
        scope_key = "global"
        semantic_target_key = _text_target_key("goal", goal_text)
        return _routed(
            route_input,
            spec=_GOAL_SPEC,
            canonical_value=_GOAL_SPEC.canonical_value,
            semantic_target_key=semantic_target_key,
            target_entity_id=None,
            target_entity_type=None,
            object_surface=str(route_input.object_value or "").strip(),
            normalized_target_text=goal_text[:200],
            goal_lineage_key=_opaque_key(
                "gln",
                {
                    "subject_type": _required(route_input.subject_type),
                    "subject_id": _required(route_input.subject_id),
                    "normalized_goal_text": goal_text,
                    "scope_key": scope_key,
                },
            ),
            target_window_key=_goal_target_window_key(route_input),
        )

    if predicate == "FEELS":
        if fact_kind not in _FEELS_SPEC.allowed_fact_kinds:
            return _mismatch(route_input, _FEELS_SPEC)
        canonical_value = _canonical_literal(predicate, route_input.object_value)
        if canonical_value is None:
            return _non_routed(
                route_input,
                disposition=RouteDisposition.UNROUTED,
                reason_code="invalid_typed_value",
                object_role=_FEELS_SPEC.object_role,
                projection_targets=_FEELS_SPEC.projection_targets,
            )
        return _routed(
            route_input,
            spec=_FEELS_SPEC,
            canonical_value=canonical_value,
            semantic_target_key="literal",
            target_entity_id=None,
            target_entity_type=None,
            object_surface=str(route_input.object_value or "").strip(),
        )

    if predicate == "HAS_METRIC":
        return _non_routed(
            route_input,
            disposition=RouteDisposition.UNROUTED,
            reason_code="typed_metric_contract_required",
            object_role=ObjectRole.STRUCTURED_TARGET_AND_VALUE,
        )

    if predicate in _DERIVED_RULE_PREDICATES:
        return _non_routed(
            route_input,
            disposition=RouteDisposition.DEFERRED,
            reason_code="derived_rule_required",
            object_role=ObjectRole.TARGET_IDENTITY,
            projection_targets=_GRAPH_ONLY,
        )

    if predicate in _RELATIONSHIP_ONLY_PREDICATES:
        return _non_routed(
            route_input,
            disposition=RouteDisposition.NOT_APPLICABLE,
            reason_code="relationship_only",
            object_role=ObjectRole.TARGET_IDENTITY,
            projection_targets=_GRAPH_ONLY,
        )

    spec = _LITERAL_SPECS.get(predicate)
    if spec is not None:
        if fact_kind not in spec.allowed_fact_kinds:
            return _mismatch(route_input, spec)
        canonical_value = _canonical_literal(predicate, route_input.object_value)
        if canonical_value is None:
            return _non_routed(
                route_input,
                disposition=RouteDisposition.UNROUTED,
                reason_code="invalid_typed_value",
                object_role=spec.object_role,
                projection_targets=spec.projection_targets,
            )
        return _routed(
            route_input,
            spec=spec,
            canonical_value=canonical_value,
            semantic_target_key="literal",
            target_entity_id=None,
            target_entity_type=None,
            object_surface=str(route_input.object_value or "").strip(),
        )

    spec = _TARGET_SPECS.get(predicate)
    if spec is not None:
        if fact_kind == "interaction_evidence":
            return _non_routed(
                route_input,
                disposition=RouteDisposition.DEFERRED,
                reason_code="derived_rule_required",
                object_role=spec.object_role,
                projection_targets=_GRAPH_ONLY,
            )
        if fact_kind not in spec.allowed_fact_kinds:
            return _mismatch(route_input, spec)
        if spec.required_object_type and object_type != spec.required_object_type:
            return _non_routed(
                route_input,
                disposition=RouteDisposition.NOT_APPLICABLE,
                reason_code="relationship_only",
                object_role=spec.object_role,
                projection_targets=_GRAPH_ONLY,
            )
        target_id = str(route_input.object_entity_id or "").strip()
        normalized_text = _normalize_semantic_text(route_input.object_value)
        if spec.object_role is ObjectRole.TARGET_IDENTITY and not target_id:
            return _non_routed(
                route_input,
                disposition=RouteDisposition.UNROUTED,
                reason_code="unresolved_target",
                object_role=spec.object_role,
                projection_targets=spec.projection_targets,
            )
        if spec.object_role is ObjectRole.TARGET_ID_OR_TEXT and not target_id and not normalized_text:
            return _non_routed(
                route_input,
                disposition=RouteDisposition.UNROUTED,
                reason_code="invalid_target_text",
                object_role=spec.object_role,
                projection_targets=spec.projection_targets,
            )
        semantic_target_key = (
            f"entity:{target_id}"
            if target_id
            else _text_target_key("text", normalized_text)
        )
        return _routed(
            route_input,
            spec=spec,
            canonical_value=spec.canonical_value,
            semantic_target_key=semantic_target_key,
            target_entity_id=target_id or None,
            target_entity_type=object_type if target_id else None,
            object_surface=str(route_input.object_value or "").strip(),
            normalized_target_text=normalized_text[:200] if normalized_text else None,
        )

    if predicate in ROUTE_DISPOSITION_BY_PREDICATE:
        raise RuntimeError(f"declared semantic route has no implementation: {predicate}")

    return _non_routed(
        route_input,
        disposition=RouteDisposition.UNROUTED,
        reason_code="unsupported_route",
        object_role=ObjectRole.UNSUPPORTED,
    )


def _routed(
    route_input: SemanticRouteInput,
    *,
    spec: _RouteSpec,
    canonical_value: Any,
    semantic_target_key: str,
    target_entity_id: str | None,
    target_entity_type: str | None,
    object_surface: str | None = None,
    normalized_target_text: str | None = None,
    goal_lineage_key: str | None = None,
    target_window_key: str | None = None,
) -> SemanticRouteDecision:
    subject_id = _required(route_input.subject_id)
    subject_type = _required(route_input.subject_type)
    scope_key = "global"
    identity: dict[str, Any] = {
        "route_contract_version": ROUTE_CONTRACT_VERSION,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "semantic_route_id": spec.semantic_route_id,
        "fact_kind": _required(route_input.fact_kind).casefold(),
        "semantic_target_key": semantic_target_key,
        "scope_key": scope_key,
    }
    route_key = _opaque_key("srk", identity)
    slot_identity: dict[str, Any] = {
        "slot_schema_version": SLOT_SCHEMA_VERSION,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "family": spec.family,
        "trait_code": spec.trait_code,
        "semantic_target_key": semantic_target_key,
        "scope_key": scope_key,
    }
    slot_key = _opaque_key(
        "slt",
        slot_identity,
    )
    return SemanticRouteDecision(
        claim_id=_required(route_input.claim_id),
        disposition=RouteDisposition.ROUTED,
        reason_code="route_supported",
        semantic_route_id=spec.semantic_route_id,
        route_key=route_key,
        slot_key=slot_key,
        family=spec.family,
        trait_code=spec.trait_code,
        object_role=spec.object_role,
        canonical_value=canonical_value,
        value_fingerprint=_opaque_key(
            "val",
            {
                "slot_key": slot_key,
                "scope_key": scope_key,
                "canonical_value": canonical_value,
            },
        ),
        subject_id=subject_id,
        subject_type=subject_type,
        target_entity_id=target_entity_id,
        target_entity_type=target_entity_type,
        object_surface=object_surface,
        normalized_target_text=normalized_target_text,
        semantic_target_key=semantic_target_key,
        goal_lineage_key=goal_lineage_key,
        target_window_key=target_window_key,
        projection_targets=spec.projection_targets,
        scope_key=scope_key,
    )


def _goal_target_window_key(route_input: SemanticRouteInput) -> str:
    resolution = str(route_input.time_resolution or "unscheduled").strip().casefold()
    raw = str(route_input.raw_time_expression or "").strip()
    epoch_window = _goal_epoch_window(route_input)
    calendar = _goal_calendar_window(route_input, resolution=resolution)
    target_window = None if calendar is not None else epoch_window
    return _opaque_key(
        "twk",
        {
            "resolution": resolution,
            "raw": raw if calendar is None and target_window is None else "",
            "calendar": calendar,
            "target_window": target_window,
        },
    )


def _goal_epoch_window(route_input: SemanticRouteInput) -> list[float] | None:
    try:
        start = float(route_input.target_from)
        end = float(route_input.target_to)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        return None
    return [start, end]


def _goal_calendar_window(
    route_input: SemanticRouteInput,
    *,
    resolution: str,
) -> dict[str, str] | None:
    """Return only complete civil semantics; provenance stays outside slot identity."""

    if resolution != "calendar_anchor" or _goal_epoch_window(route_input) is None:
        return None
    if not isinstance(route_input.time_frame, Mapping):
        return None
    raw_calendar = route_input.time_frame.get("calendar")
    if not isinstance(raw_calendar, Mapping):
        return None
    if canonical_timezone_id(raw_calendar.get("timezone_id")) is None:
        return None
    precision = str(raw_calendar.get("precision") or "").strip().casefold()
    if precision not in {"day", "week", "month"}:
        return None
    raw_civil_start = str(raw_calendar.get("civil_start") or "").strip()
    raw_civil_end = str(raw_calendar.get("civil_end_exclusive") or "").strip()
    try:
        civil_start = date.fromisoformat(raw_civil_start)
        civil_end = date.fromisoformat(raw_civil_end)
        if civil_end <= civil_start:
            return None
    except ValueError:
        return None
    return {
        "precision": precision,
        "civil_start": civil_start.isoformat(),
        "civil_end_exclusive": civil_end.isoformat(),
    }


def _mismatch(
    route_input: SemanticRouteInput,
    spec: _RouteSpec,
) -> SemanticRouteDecision:
    return _non_routed(
        route_input,
        disposition=RouteDisposition.UNROUTED,
        reason_code="predicate_fact_kind_mismatch",
        object_role=spec.object_role,
        projection_targets=spec.projection_targets,
    )


def _non_routed(
    route_input: SemanticRouteInput,
    *,
    disposition: RouteDisposition,
    reason_code: str,
    object_role: ObjectRole,
    projection_targets: frozenset[ProjectionTarget] = frozenset(),
) -> SemanticRouteDecision:
    return SemanticRouteDecision(
        claim_id=_required(route_input.claim_id),
        disposition=disposition,
        reason_code=reason_code,
        object_role=object_role,
        projection_targets=projection_targets,
        subject_id=_required(route_input.subject_id),
        subject_type=_required(route_input.subject_type),
    )


def _canonical_literal(predicate: str, value: Any) -> Any | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = " ".join(text.split())
    if not text:
        return None
    if predicate == "BIRTH_DATE":
        match = _BIRTH_DATE.fullmatch(text)
        if match is None:
            return None
        year_text = match.group("year")
        year = int(year_text or 2000)
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            date(year, month, day)
        except ValueError:
            return None
        if year_text is not None:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return f"{month:02d}-{day:02d}"
    if predicate == "BIRTH_YEAR":
        if _ASCII_INTEGER.fullmatch(text) is None:
            return None
        year = int(text)
        return year if 1900 <= year <= 2200 else None
    if predicate in {"AGE", "STATED_AGE"}:
        if _ASCII_INTEGER.fullmatch(text) is None:
            return None
        age = int(text)
        return age if 0 <= age <= 130 else None
    return text[:200]


def _normalize_semantic_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return " ".join(text.split())


def _text_target_key(prefix: str, normalized_text: str) -> str:
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _opaque_key(prefix: str, material: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


def _required(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("semantic route input contains a blank required field")
    return text


__all__ = [
    "ObjectRole",
    "ProjectionTarget",
    "ROUTE_CONTRACT_VERSION",
    "ROUTE_DISPOSITION_BY_PREDICATE",
    "ROUTE_EXTENSION_PREDICATES",
    "RouteDisposition",
    "SLOT_SCHEMA_VERSION",
    "SemanticRouteDecision",
    "SemanticRouteInput",
    "derive_semantic_route",
]
