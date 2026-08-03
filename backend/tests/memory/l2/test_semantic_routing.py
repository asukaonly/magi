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
        "HAS_METRIC",
        "MAINTAINS",
        "PREFERRED_COMMUNICATION_STYLE",
        "PREFERRED_FORM_OF_ADDRESS",
        "REAL_NAME",
        "STATED_AGE",
        "WORKS_ON",
    }
)
_DEFERRED_PREDICATES = frozenset(
    {
        "ATTENDED",
        "CHECKED_OUT",
        "COMMITTED",
        "EXECUTED",
        "FOLLOWS",
        "LISTENED",
        "MERGED",
        "PLANS_TO",
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
    elif predicate in _DEFERRED_PREDICATES:
        fact_kind = "future_intent" if predicate == "PLANS_TO" else "interaction_evidence"
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
    }
    values.update(overrides)
    return SemanticRouteInput(**values)  # type: ignore[arg-type]


def test_route_disposition_table_exhausts_catalog_and_profile_signals() -> None:
    expected = {
        **dict.fromkeys(_ROUTED_PREDICATES, RouteDisposition.ROUTED),
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


def test_target_route_never_falls_back_to_object_surface() -> None:
    for surface in ("Jazz", "爵士乐", "  jazz music  "):
        decision = derive_semantic_route(
            _route_input(
                "LIKES",
                claim_id=f"claim:{surface}",
                object_value=surface,
                object_entity_id=None,
            )
        )

        assert decision.disposition is RouteDisposition.UNROUTED
        assert decision.reason_code == "unresolved_target"
        assert decision.route_key is None
        assert decision.slot_key is None
        assert decision.canonical_value is None
        assert not decision.can_project_assertion


def test_unknown_predicate_remains_visible_as_unrouted() -> None:
    decision = derive_semantic_route(_route_input("ALLERGIC_TO"))

    assert decision.disposition is RouteDisposition.UNROUTED
    assert decision.reason_code == "unsupported_route"
    assert decision.slot_key is None
    assert not decision.can_project_assertion
