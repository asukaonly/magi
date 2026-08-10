"""Contract tests for host-owned L2 semantic routing."""

from __future__ import annotations

from dataclasses import replace

import pytest

from magi.memory.l2 import semantic_routing
from magi.memory.l2.ontology import PROFILE_SIGNAL_PREDICATES
from magi.memory.l2.ontology_aliases import (
    PREDICATE_ALIASES,
    canonicalize_predicate,
)
from magi.memory.l2.predicate_catalog import ALL_SPECS, SPEC_BY_CANONICAL
from magi.memory.l2.semantic_routing import (
    ObjectRole,
    ProjectionTarget,
    ROUTE_DISPOSITION_BY_PREDICATE,
    ROUTE_EXTENSION_PREDICATES,
    RouteDisposition,
    SemanticRouteInput,
    derive_semantic_route,
)

_ROUTED_PREDICATES = frozenset(
    {
        "AGE",
        "BIRTH_DATE",
        "BIRTH_YEAR",
        "CREATES",
        "CONTRIBUTES_TO",
        "DEVELOPS",
        "DISALLOWED_FORM_OF_ADDRESS",
        "DISLIKES",
        "INTERESTED_IN",
        "LIKES",
        "FEELS",
        "MAINTAINS",
        "PLANS_TO",
        "PREFERRED_COMMUNICATION_STYLE",
        "PREFERRED_FORM_OF_ADDRESS",
        "REAL_NAME",
        "STATED_AGE",
        "WORKS_ON",
    }
)
_UNROUTED_PREDICATES = frozenset({"HAS_METRIC"})
_DEFERRED_PREDICATES = frozenset(
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
_NOT_APPLICABLE_PREDICATES = frozenset(
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

_PROFILE_VALUES = {
    "AGE": "29",
    "BIRTH_DATE": "1997-04-03",
    "BIRTH_YEAR": "1997",
    "DISALLOWED_FORM_OF_ADDRESS": "sir",
    "PREFERRED_COMMUNICATION_STYLE": "concise",
    "PREFERRED_FORM_OF_ADDRESS": "Asuka",
    "REAL_NAME": "Asuka",
    "STATED_AGE": "29",
}


def _route_input(predicate: str, **overrides: object) -> SemanticRouteInput:
    fact_kind = "explicit_fact"
    object_type = "other"
    object_entity_id: str | None = None
    object_value: object = _PROFILE_VALUES.get(predicate, "target surface")

    if predicate in {"LIKES", "DISLIKES", "INTERESTED_IN"}:
        object_type = "topic"
        object_entity_id = "entity:jazz"
    elif predicate in {"CONTRIBUTES_TO", "CREATES", "DEVELOPS", "MAINTAINS", "WORKS_ON"}:
        object_type = "project"
        object_entity_id = "entity:magi"
    elif predicate == "FEELS":
        object_value = "calm"
    elif predicate == "HAS_METRIC":
        object_type = "health_metric"
        object_value = "stress"
    elif predicate == "PLANS_TO":
        fact_kind = "future_intent"
        object_type = "activity"
        object_entity_id = "entity:target"
    elif predicate in _DEFERRED_PREDICATES:
        fact_kind = "interaction_evidence"
        object_entity_id = "entity:target"

    values: dict[str, object] = {
        "claim_id": f"claim:{predicate.casefold()}",
        "subject_id": "person:user",
        "subject_type": "person",
        "canonical_predicate": predicate,
        "fact_kind": fact_kind,
        "object_type": object_type,
        "object_value": object_value,
        "object_entity_id": object_entity_id,
        "temporal_cue": "current",
        "specificity": "concrete",
        "target_from": None,
        "target_to": None,
        "raw_time_expression": "",
        "time_resolution": "unscheduled",
    }
    values.update(overrides)
    return SemanticRouteInput(**values)  # type: ignore[arg-type]


def test_route_disposition_table_exhausts_catalog_and_profile_signals() -> None:
    expected = {
        **dict.fromkeys(_ROUTED_PREDICATES, RouteDisposition.ROUTED),
        **dict.fromkeys(_UNROUTED_PREDICATES, RouteDisposition.UNROUTED),
        **dict.fromkeys(_DEFERRED_PREDICATES, RouteDisposition.DEFERRED),
        **dict.fromkeys(
            _NOT_APPLICABLE_PREDICATES,
            RouteDisposition.NOT_APPLICABLE,
        ),
    }
    known_predicates = (
        set(SPEC_BY_CANONICAL).union(PROFILE_SIGNAL_PREDICATES).union(ROUTE_EXTENSION_PREDICATES)
    )

    assert set(expected) == known_predicates
    assert dict(ROUTE_DISPOSITION_BY_PREDICATE) == expected

    for predicate, disposition in expected.items():
        decision = derive_semantic_route(_route_input(predicate))
        assert decision.disposition is disposition, predicate
        assert decision.can_project_assertion is (disposition is RouteDisposition.ROUTED), predicate


def test_metric_route_waits_for_a_host_typed_value_contract() -> None:
    first = derive_semantic_route(_route_input("HAS_METRIC", object_value="stress"))
    second = derive_semantic_route(_route_input("HAS_METRIC", object_value="engagement"))

    for decision in (first, second):
        assert decision.disposition is RouteDisposition.UNROUTED
        assert decision.reason_code == "typed_metric_contract_required"
        assert decision.object_role is semantic_routing.ObjectRole.STRUCTURED_TARGET_AND_VALUE
        assert decision.slot_key is None
        assert decision.value_fingerprint is None


@pytest.mark.parametrize("value", ["2020-02-29", "02-29", "1997-04-03"])
def test_birth_date_accepts_real_calendar_dates(value: str) -> None:
    decision = derive_semantic_route(_route_input("BIRTH_DATE", object_value=value))

    assert decision.disposition is RouteDisposition.ROUTED
    assert decision.canonical_value == value


@pytest.mark.parametrize(
    "value",
    ["2021-02-29", "2020-02-31", "04-31", "13-01", "٢٠٢٠-02-29"],
)
def test_birth_date_rejects_invalid_typed_values(value: str) -> None:
    decision = derive_semantic_route(_route_input("BIRTH_DATE", object_value=value))

    assert decision.disposition is RouteDisposition.UNROUTED
    assert decision.reason_code == "invalid_typed_value"


@pytest.mark.parametrize(
    ("predicate", "value"),
    [
        ("BIRTH_YEAR", "፩፱፱፯"),
        ("STATED_AGE", "፫፬"),
    ],
)
def test_integer_literals_reject_non_ascii_digit_scripts_without_raising(
    predicate: str,
    value: str,
) -> None:
    decision = derive_semantic_route(_route_input(predicate, object_value=value))

    assert decision.disposition is RouteDisposition.UNROUTED
    assert decision.reason_code == "invalid_typed_value"


def test_predicate_catalog_aliases_match_canonicalizer() -> None:
    catalog_aliases = {alias: spec.canonical for spec in ALL_SPECS for alias in spec.aliases}

    assert {alias: PREDICATE_ALIASES.get(alias) for alias in catalog_aliases} == catalog_aliases
    assert {spec.canonical: canonicalize_predicate(spec.canonical) for spec in ALL_SPECS} == {
        spec.canonical: spec.canonical for spec in ALL_SPECS
    }


def test_age_profile_signal_canonicalizes_to_stated_age() -> None:
    assert PREDICATE_ALIASES["AGE"] == "STATED_AGE"
    assert canonicalize_predicate("AGE") == "STATED_AGE"
    assert canonicalize_predicate(" age ") == "STATED_AGE"

    legacy = derive_semantic_route(_route_input("AGE"))
    canonical = derive_semantic_route(_route_input("STATED_AGE"))
    assert legacy.slot_key == canonical.slot_key
    assert legacy.route_key == canonical.route_key
    assert legacy.canonical_value == canonical.canonical_value == 29


def test_likes_and_dislikes_share_target_slot_but_not_value() -> None:
    likes = derive_semantic_route(_route_input("LIKES"))
    dislikes = derive_semantic_route(_route_input("DISLIKES"))

    assert likes.slot_key == dislikes.slot_key
    assert likes.route_key == dislikes.route_key
    assert likes.family == dislikes.family == "preference_profile"
    assert likes.trait_code == dislikes.trait_code == "preference.affinity"
    assert likes.canonical_value == "like"
    assert dislikes.canonical_value == "dislike"
    assert likes.value_fingerprint != dislikes.value_fingerprint


@pytest.mark.parametrize("predicate", ["LIKES", "DISLIKES"])
def test_one_off_preference_routes_to_assertion_without_graph(
    predicate: str,
) -> None:
    decision = derive_semantic_route(_route_input(predicate, temporal_cue="one_off"))

    assert decision.disposition is RouteDisposition.ROUTED
    assert decision.can_project_assertion is True
    assert decision.can_project_graph is False
    assert decision.projection_targets == frozenset({ProjectionTarget.ASSERTION})


def test_slot_identity_ignores_fact_kind_temporal_route_version_and_surface_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_input = _route_input("LIKES")
    baseline = derive_semantic_route(route_input)
    variants = [
        replace(route_input, claim_id="claim:fact", fact_kind="stable_preference"),
        replace(route_input, claim_id="claim:time", temporal_cue="historical"),
        replace(route_input, claim_id="claim:surface", object_value="爵士乐"),
    ]
    fact_variant = derive_semantic_route(variants[0])
    temporal_variant = derive_semantic_route(variants[1])
    surface_variant = derive_semantic_route(variants[2])

    assert fact_variant.route_key != baseline.route_key
    assert temporal_variant.route_key == baseline.route_key
    assert surface_variant.route_key == baseline.route_key

    monkeypatch.setattr(
        semantic_routing,
        "ROUTE_CONTRACT_VERSION",
        semantic_routing.ROUTE_CONTRACT_VERSION + 1,
    )
    route_version_variant = replace(route_input, claim_id="claim:route-version")
    variants.append(route_version_variant)

    assert baseline.slot_key is not None
    assert {derive_semantic_route(item).slot_key for item in variants} == {baseline.slot_key}
    assert derive_semantic_route(route_version_variant).route_key != baseline.route_key

    first_name = derive_semantic_route(_route_input("REAL_NAME", object_value="Asuka"))
    changed_name = derive_semantic_route(
        _route_input("REAL_NAME", claim_id="claim:new-name", object_value="A. Suka")
    )
    assert first_name.slot_key == changed_name.slot_key
    assert first_name.value_fingerprint != changed_name.value_fingerprint


def test_preference_route_uses_text_identity_when_entity_resolution_is_missing() -> None:
    for surface in ("Jazz", "爵士乐", "  jazz music  "):
        decision = derive_semantic_route(
            _route_input(
                "LIKES",
                claim_id=f"claim:{surface}",
                object_value=surface,
                object_entity_id=None,
            )
        )

        assert decision.disposition is RouteDisposition.ROUTED
        assert decision.object_role is ObjectRole.TARGET_ID_OR_TEXT
        assert decision.semantic_target_key
        assert decision.semantic_target_key.startswith("text:")
        assert decision.normalized_target_text == " ".join(surface.casefold().split())
        assert decision.target_entity_id is None
        assert decision.can_project_assertion
        assert not decision.can_project_graph


def test_text_target_hash_uses_full_normalized_text_beyond_display_limit() -> None:
    shared_prefix = "x" * 200
    first = derive_semantic_route(
        _route_input("LIKES", object_value=shared_prefix + "a", object_entity_id=None)
    )
    second = derive_semantic_route(
        _route_input(
            "LIKES",
            claim_id="claim:second",
            object_value=shared_prefix + "b",
            object_entity_id=None,
        )
    )

    assert first.normalized_target_text == second.normalized_target_text == shared_prefix
    assert first.semantic_target_key != second.semantic_target_key
    assert first.slot_key != second.slot_key


def test_resolved_preference_declares_graph_and_assertion_projection() -> None:
    decision = derive_semantic_route(_route_input("LIKES"))

    assert decision.semantic_target_key == "entity:entity:jazz"
    assert decision.projection_targets == frozenset(
        {ProjectionTarget.GRAPH, ProjectionTarget.ASSERTION}
    )
    assert decision.can_project_assertion
    assert decision.can_project_graph


def test_goal_route_requires_concrete_text_and_keeps_window_out_of_slot() -> None:
    unscheduled = derive_semantic_route(_route_input("PLANS_TO"))
    scheduled = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            claim_id="claim:scheduled",
            target_from=1_800_000_000.0,
            target_to=1_800_086_400.0,
            raw_time_expression="2027-01-15",
            time_resolution="calendar_anchor",
            time_frame={
                "calendar": {
                    "timezone_id": "Asia/Shanghai",
                    "precision": "day",
                    "civil_start": "2027-01-15",
                    "civil_end_exclusive": "2027-01-16",
                    "operator": "absolute",
                    "anchor_event_ids": [],
                }
            },
        )
    )

    assert unscheduled.disposition is RouteDisposition.ROUTED
    assert unscheduled.family == "goal_profile"
    assert unscheduled.trait_code == "goal.intent"
    assert unscheduled.object_role is ObjectRole.GOAL_TEXT
    assert unscheduled.target_entity_id is None
    assert unscheduled.semantic_target_key
    assert unscheduled.goal_lineage_key
    assert unscheduled.target_window_key
    assert scheduled.slot_key == unscheduled.slot_key
    assert scheduled.goal_lineage_key == unscheduled.goal_lineage_key
    assert scheduled.target_window_key != unscheduled.target_window_key

    blank = derive_semantic_route(_route_input("PLANS_TO", object_value=" ", object_entity_id=None))
    vague = derive_semantic_route(_route_input("PLANS_TO", specificity="underspecified"))
    assert blank.reason_code == "invalid_goal_text"
    assert vague.reason_code == "goal_target_not_concrete"


def test_goal_window_identity_uses_civil_descriptor_instead_of_runtime_epoch() -> None:
    frame = {
        "calendar": {
            "timezone_id": "Asia/Shanghai",
            "precision": "day",
            "civil_start": "2027-01-15",
            "civil_end_exclusive": "2027-01-16",
            "operator": "absolute",
            "anchor_event_ids": [],
        }
    }
    first = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            target_from=1_800_000_000.0,
            target_to=1_800_086_400.0,
            raw_time_expression="2027-01-15",
            time_resolution="calendar_anchor",
            time_frame=frame,
        )
    )
    shifted_epoch = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            claim_id="claim:shifted-runtime",
            target_from=1_800_028_800.0,
            target_to=1_800_115_200.0,
            raw_time_expression="2027-01-15",
            time_resolution="calendar_anchor",
            time_frame=frame,
        )
    )
    synonymous_expression = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            claim_id="claim:synonymous-expression",
            target_from=1_800_000_000.0,
            target_to=1_800_086_400.0,
            raw_time_expression="tomorrow",
            time_resolution="calendar_anchor",
            time_frame={
                "calendar": {
                    **frame["calendar"],
                    "operator": "tomorrow",
                    "anchor_event_ids": ["evt-2"],
                }
            },
        )
    )
    timezone_alias = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            claim_id="claim:timezone-alias",
            target_from=1_800_000_000.0,
            target_to=1_800_086_400.0,
            raw_time_expression="2027-01-15",
            time_resolution="calendar_anchor",
            time_frame={
                "calendar": {
                    **frame["calendar"],
                    "timezone_id": "PRC",
                }
            },
        )
    )
    different_day = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            claim_id="claim:different-day",
            raw_time_expression="2027-01-16",
            time_resolution="calendar_anchor",
            time_frame={
                "calendar": {
                    **frame["calendar"],
                    "civil_start": "2027-01-16",
                    "civil_end_exclusive": "2027-01-17",
                }
            },
        )
    )

    assert first.target_window_key == shifted_epoch.target_window_key
    assert first.slot_key == shifted_epoch.slot_key
    assert first.target_window_key == synonymous_expression.target_window_key
    assert first.slot_key == synonymous_expression.slot_key
    assert first.target_window_key == timezone_alias.target_window_key
    assert first.slot_key == timezone_alias.slot_key
    assert different_day.target_window_key != first.target_window_key
    assert different_day.slot_key == first.slot_key


def test_goal_window_audit_identity_falls_back_to_resolved_epochs() -> None:
    first = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            claim_id="claim:legacy-first",
            target_from=1_800_000_000.0,
            target_to=1_800_086_400.0,
            raw_time_expression="tomorrow",
            time_resolution="calendar_anchor",
            time_frame={
                "raw": "tomorrow",
                "kind": "target",
                "resolution": "calendar_anchor",
                "resolved_range": [1_800_000_000.0, 1_800_086_400.0],
            },
        )
    )
    different_window = derive_semantic_route(
        _route_input(
            "PLANS_TO",
            claim_id="claim:legacy-later",
            target_from=1_800_086_400.0,
            target_to=1_800_172_800.0,
            raw_time_expression="tomorrow",
            time_resolution="calendar_anchor",
            time_frame={
                "raw": "tomorrow",
                "kind": "target",
                "resolution": "calendar_anchor",
                "resolved_range": [1_800_086_400.0, 1_800_172_800.0],
            },
        )
    )

    assert first.target_window_key != different_window.target_window_key
    assert first.slot_key == different_window.slot_key


def test_unknown_predicate_remains_visible_as_unrouted() -> None:
    decision = derive_semantic_route(_route_input("ALLERGIC_TO"))

    assert decision.disposition is RouteDisposition.UNROUTED
    assert decision.reason_code == "unsupported_route"
    assert decision.slot_key is None
    assert not decision.can_project_assertion
