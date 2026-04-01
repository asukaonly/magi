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


def test_validator_can_identify_leaf_level_duplicates():
    from magi.memory.l2.ontology import is_leaf_fact_duplicate

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
    from magi.memory.l2.ontology import is_leaf_fact_duplicate

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
    from magi.memory.l2.ontology import is_leaf_fact_duplicate

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
