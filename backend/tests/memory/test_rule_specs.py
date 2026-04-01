"""Tests for hybrid retrieval rule specs."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.rule_specs import (
    extract_location_constraint,
    infer_source_domain_filters,
    infer_semantic_constraints,
)


def test_infer_semantic_constraints_extracts_location() -> None:
    place_constraints = infer_semantic_constraints("我在杭州的时候喜欢去哪些咖啡馆")
    assert [(item.scope, item.facet, item.raw_value) for item in place_constraints] == [
        ("interaction", "located_in", "杭州"),
    ]


def test_extract_location_constraint_distinguishes_target_and_interaction_scope() -> None:
    interaction_constraint = extract_location_constraint("我在杭州的时候喜欢去哪些咖啡馆")
    assert interaction_constraint is not None
    assert (interaction_constraint.scope, interaction_constraint.facet, interaction_constraint.raw_value) == (
        "interaction", "located_in", "杭州"
    )

    target_constraint = extract_location_constraint("我在杭州喜欢去哪些咖啡馆")
    assert target_constraint is not None
    assert (target_constraint.scope, target_constraint.facet, target_constraint.raw_value) == (
        "target", "located_in", "杭州"
    )


def test_infer_source_domain_filters_uses_central_specs() -> None:
    assert infer_source_domain_filters("我浏览了什么网页") == (["chrome_history"], ["external_activity"])
    assert infer_source_domain_filters("我们刚才聊天聊了什么") == (["chat"], ["user_authored"])
