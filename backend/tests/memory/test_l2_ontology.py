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

