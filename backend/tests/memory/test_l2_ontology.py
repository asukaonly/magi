from __future__ import annotations

import pytest


def test_normalize_entity_type_maps_dish_to_food():
    from magi.memory.l2_ontology import normalize_entity_type

    assert normalize_entity_type("dish") == "food"


def test_coerce_unknown_entity_type_falls_back_to_other():
    from magi.memory.l2_ontology import coerce_unknown_entity_type

    assert coerce_unknown_entity_type("mystery_type") == "other"


def test_none_is_not_a_valid_entity_type():
    from magi.memory.l2_ontology import is_valid_entity_type

    assert is_valid_entity_type("none") is False


@pytest.mark.parametrize(
    ("predicate", "object_type", "expected"),
    [
        ("DISLIKES", "food", True),
        ("DISLIKES", "health_metric", False),
        ("HAS_METRIC", "health_metric", True),
        ("LIVES_IN", "place", True),
        ("LIVES_IN", "organization", False),
    ],
)
def test_predicate_compatibility_matrix(predicate: str, object_type: str, expected: bool):
    from magi.memory.l2_ontology import is_predicate_compatible

    assert is_predicate_compatible(predicate, object_type) is expected


def test_validator_rejects_unknown_graph_predicate():
    from magi.memory.l2_ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "ADORES",
            "object_type": "food",
        }
    )

    assert is_valid is False
    assert reason == "invalid_predicate"


def test_validator_rejects_illegal_graph_object_type_combination():
    from magi.memory.l2_ontology import validate_graph_candidate

    is_valid, reason = validate_graph_candidate(
        {
            "predicate": "DISLIKES",
            "object_type": "health_metric",
        }
    )

    assert is_valid is False
    assert reason == "invalid_object_type"


def test_validator_rejects_unsupported_assertion_family():
    from magi.memory.l2_ontology import validate_assertion_candidate

    is_valid, reason = validate_assertion_candidate(
        {
            "trait_family": "personality_core",
        }
    )

    assert is_valid is False
    assert reason == "invalid_trait_family"


def test_validator_can_identify_leaf_level_duplicates():
    from magi.memory.l2_ontology import is_leaf_fact_duplicate

    duplicate = is_leaf_fact_duplicate(
        graph_candidates=[
            {
                "predicate": "DISLIKES",
                "object_ref": "food:west-lake-vinegar-fish",
            }
        ],
        assertion_candidate={
            "trait_name": "taste_preference",
            "trait_value": "dislikes_food:food:west-lake-vinegar-fish",
        },
    )

    assert duplicate is True


def test_validator_can_identify_generic_leaf_preference_duplicates():
    from magi.memory.l2_ontology import is_leaf_fact_duplicate

    duplicate = is_leaf_fact_duplicate(
        graph_candidates=[
            {
                "predicate": "LIKES",
                "object_ref": "technology:rust",
            }
        ],
        assertion_candidate={
            "trait_name": "preference",
            "trait_value": "likes_technology:technology:rust",
        },
    )

    assert duplicate is True


def test_validator_allows_higher_order_assertion_alongside_graph_fact():
    from magi.memory.l2_ontology import is_leaf_fact_duplicate

    duplicate = is_leaf_fact_duplicate(
        graph_candidates=[
            {
                "predicate": "DISLIKES",
                "object_ref": "food:west-lake-vinegar-fish",
            }
        ],
        assertion_candidate={
            "trait_name": "taste_profile",
            "trait_value": "avoids_vinegar_heavy_dishes",
        },
    )

    assert duplicate is False
