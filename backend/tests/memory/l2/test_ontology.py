from __future__ import annotations

import pytest


def test_normalize_entity_type_maps_dish_to_food():
    from magi.memory.l2.ontology import normalize_entity_type

    assert normalize_entity_type("dish") == "food"


def test_coerce_unknown_entity_type_falls_back_to_other():
    from magi.memory.l2.ontology import coerce_unknown_entity_type

    assert coerce_unknown_entity_type("mystery_type") == "other"


def test_none_is_not_a_valid_entity_type():
    from magi.memory.l2.ontology import is_valid_entity_type

    assert is_valid_entity_type("none") is False


@pytest.mark.parametrize(
    ("predicate", "object_type", "expected"),
    [
        ("DISLIKES", "food", True),
        ("DISLIKES", "health_metric", True),
        ("HAS_METRIC", "health_metric", True),
        ("HAS_METRIC", "food", False),
        ("LIVES_IN", "place", True),
        ("LIVES_IN", "organization", False),
        ("VISITED", "virtual_object", True),
        ("ON_PLATFORM", "food", False),
    ],
)
def test_predicate_compatibility_matrix(predicate: str, object_type: str, expected: bool):
    from magi.memory.l2.ontology import is_predicate_compatible

    assert is_predicate_compatible(predicate, object_type) is expected


def test_validator_rejects_malformed_graph_predicate():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "adores food",
            "object_type": "food",
        }
    )

    assert is_valid is False
    assert reason == "invalid_predicate"


def test_validator_accepts_open_predicate_upper_snake_case():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "ALLERGIC_TO",
            "object_type": "food",
        }
    )

    assert is_valid is True
    assert reason is None


def test_validator_rejects_low_value_open_predicate():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "ASKED_ABOUT",
            "object_type": "software",
            "object_ref": "GitHub",
        }
    )

    assert is_valid is False
    assert reason == "low_value_predicate"


def test_validator_rejects_vague_graph_object():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "MAINTAINS",
            "object_type": "software",
            "object_ref": "那个",
        }
    )

    assert is_valid is False
    assert reason == "vague_entity_reference"


def test_validator_rejects_assertion_family_as_graph_predicate():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "PREFERENCE_PROFILE",
            "object_type": "concept",
            "object_ref": "子涵",
        }
    )

    assert is_valid is False
    assert reason == "reserved_assertion_predicate"


def test_validator_rejects_profile_signal_as_graph_predicate():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "PREFERRED_FORM_OF_ADDRESS",
            "object_type": "concept",
            "object_ref": "子涵",
        }
    )

    assert is_valid is False
    assert reason == "profile_signal_predicate"


def test_profile_signal_predicate_aliases_are_canonicalized():
    from magi.memory.l2.ontology_aliases import canonicalize_predicate

    assert canonicalize_predicate("PREFERRED_ADDRESS") == "PREFERRED_FORM_OF_ADDRESS"
    assert canonicalize_predicate("call me") == "PREFERRED_FORM_OF_ADDRESS"
    assert canonicalize_predicate("name") == "REAL_NAME"


def test_validator_rejects_internal_assertion_identifier_as_graph_object():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "LIKES",
            "object_type": "concept",
            "object_ref": "preference.address.preferred",
        }
    )

    assert is_valid is False
    assert reason == "reserved_assertion_identifier"


def test_reserved_assertion_identifier_guard_is_namespace_based():
    from magi.memory.l2.ontology import is_reserved_assertion_graph_identifier

    assert is_reserved_assertion_graph_identifier("concept:preference-address-preferred") is True
    assert is_reserved_assertion_graph_identifier("stress.level.current") is True
    assert is_reserved_assertion_graph_identifier("preference_profile") is True
    assert is_reserved_assertion_graph_identifier("concept:mood-board") is False
    assert is_reserved_assertion_graph_identifier("concept:mood-board-blue") is False


def test_validator_rejects_illegal_graph_object_type_combination():
    from magi.memory.l2.ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "HAS_METRIC",
            "object_type": "food",
        }
    )

    assert is_valid is False
    assert reason == "invalid_object_type"


def test_validator_rejects_unsupported_assertion_family():
    from magi.memory.l2.ontology import validate_assertion_candidate

    is_valid, reason = validate_assertion_candidate(
        {
            "trait_family": "personality_core",
        }
    )

    assert is_valid is False
    assert reason == "invalid_trait_family"


def test_validator_rejects_removed_taste_profile_family():
    from magi.memory.l2.ontology import validate_assertion_candidate

    is_valid, reason = validate_assertion_candidate(
        {
            "trait_family": "taste_profile",
        }
    )

    assert is_valid is False
    assert reason == "invalid_trait_family"


# ── _PREDICATE_SYNONYM_GROUPS ──


def test_are_predicates_synonymous_same_group():
    from magi.memory.l2.ontology import are_predicates_synonymous

    assert are_predicates_synonymous("LIKES", "INTERESTED_IN") is True
    assert are_predicates_synonymous("USES", "WORKS_WITH") is True
    assert are_predicates_synonymous("VISITED", "ATTENDED") is True


def test_are_predicates_synonymous_different_group():
    from magi.memory.l2.ontology import are_predicates_synonymous

    # LIKES (affinity) vs DISLIKES (aversion) – different groups
    assert are_predicates_synonymous("LIKES", "DISLIKES") is False
    # USES (usage) vs LIKES (affinity) – different groups
    assert are_predicates_synonymous("USES", "LIKES") is False


def test_are_predicates_synonymous_ungrouped():
    from magi.memory.l2.ontology import are_predicates_synonymous

    # HAS_METRIC is not in any synonym group
    assert are_predicates_synonymous("HAS_METRIC", "LIKES") is False
    # Two ungrouped predicates
    assert are_predicates_synonymous("CREATES", "OWNS") is False


def test_get_predicate_synonym_group():
    from magi.memory.l2.ontology import get_predicate_synonym_group

    assert get_predicate_synonym_group("LIKES") == "affinity"
    assert get_predicate_synonym_group("DISLIKES") == "aversion"
    assert get_predicate_synonym_group("HAS_METRIC") is None


# ── Semi-open predicates ──


def test_is_valid_open_predicate_accepts_upper_snake_case():
    from magi.memory.l2.ontology import is_valid_open_predicate

    assert is_valid_open_predicate("LEARNING") is True
    assert is_valid_open_predicate("ALLERGIC_TO") is True
    assert is_valid_open_predicate("HAS_2_CATS") is True


def test_low_value_open_predicates_are_identified():
    from magi.memory.l2.ontology import is_low_value_open_predicate

    assert is_low_value_open_predicate("ASKED_ABOUT") is True
    assert is_low_value_open_predicate("mentioned") is True
    assert is_low_value_open_predicate("MAINTAINS") is False


def test_vague_entity_references_are_identified():
    from magi.memory.l2.ontology import is_vague_entity_reference

    assert is_vague_entity_reference("那个") is True
    assert is_vague_entity_reference("person:他") is True
    assert is_vague_entity_reference("software:app") is True
    assert is_vague_entity_reference("person:德克萨斯") is False


def test_is_valid_open_predicate_rejects_invalid_formats():
    from magi.memory.l2.ontology import is_valid_open_predicate

    assert is_valid_open_predicate("learning") is False
    assert is_valid_open_predicate("foo bar") is False
    assert is_valid_open_predicate("") is False
    assert is_valid_open_predicate("_LEADING") is False


def test_open_predicate_confidence_penalty():
    from magi.memory.l2.ontology import OPEN_PREDICATE_CONFIDENCE_PENALTY

    assert OPEN_PREDICATE_CONFIDENCE_PENALTY == 0.7


# ── FAMILY_TO_PREDICATES & expand_predicate_group ──


def test_family_to_predicates_covers_all_retrieval_families():
    from magi.memory.l2.ontology import FAMILY_TO_PREDICATES

    assert "preference" in FAMILY_TO_PREDICATES
    assert "relationship" in FAMILY_TO_PREDICATES
    assert "activity" in FAMILY_TO_PREDICATES
    assert "profile_fact" in FAMILY_TO_PREDICATES


def test_preference_family_includes_follows():
    from magi.memory.l2.ontology import FAMILY_TO_PREDICATES

    assert "FOLLOWS" in FAMILY_TO_PREDICATES["preference"]


def test_activity_family_includes_uses_and_visited():
    from magi.memory.l2.ontology import FAMILY_TO_PREDICATES

    assert "USES" in FAMILY_TO_PREDICATES["activity"]
    assert "VISITED" in FAMILY_TO_PREDICATES["activity"]


def test_expand_predicate_group_adds_synonyms():
    from magi.memory.l2.ontology import expand_predicate_group

    expanded = expand_predicate_group(["LIKES"])
    assert "INTERESTED_IN" in expanded  # same "affinity" group
    assert "LIKES" in expanded


def test_expand_predicate_group_preserves_non_grouped():
    from magi.memory.l2.ontology import expand_predicate_group

    expanded = expand_predicate_group(["LIKES", "CREATES"])
    assert "CREATES" in expanded
    assert "LIKES" in expanded
    assert "INTERESTED_IN" in expanded


def test_expand_predicate_group_expands_usage_group():
    from magi.memory.l2.ontology import expand_predicate_group

    expanded = expand_predicate_group(["USES"])
    assert "WORKS_WITH" in expanded
    assert "USES" in expanded


def test_predicates_for_family_returns_expanded_set():
    from magi.memory.l2.ontology import predicates_for_family

    preds = predicates_for_family("activity")
    assert preds is not None
    assert "USES" in preds
    assert "WORKS_WITH" in preds  # expanded from USES synonym group
    assert "VISITED" in preds
    assert "ATTENDED" in preds  # expanded from VISITED synonym group


def test_predicates_for_family_returns_none_for_unknown():
    from magi.memory.l2.ontology import predicates_for_family

    assert predicates_for_family("nonexistent") is None
