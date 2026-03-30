"""Tests for hybrid retrieval rule specs."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.rule_specs import (
    extract_answer_object_mentions,
    extract_category_constraint,
    extract_location_constraint,
    extract_platform_constraint,
    infer_answer_kind,
    infer_answer_shape,
    infer_polarity,
    infer_semantic_constraints,
)


def test_infer_answer_kind_uses_central_keyword_specs() -> None:
    assert infer_answer_kind("我喜欢哪些频道") == "creator"
    assert infer_answer_kind("我喜欢什么题材") == "topic"
    assert infer_answer_kind("我喜欢B站吗") == "software"
    assert infer_answer_kind("上次我看的主播他说的主题是什么") == "topic"


def test_infer_answer_shape_uses_central_query_specs() -> None:
    assert infer_answer_shape("我喜欢什么题材") == "list"
    assert infer_answer_shape("我喜欢B站吗") == "boolean"
    assert infer_answer_shape("上次我看的主播他说的主题是什么") == "list"
    assert infer_answer_shape("我最喜欢的up主") == "single"


def test_infer_polarity_uses_central_keyword_specs() -> None:
    assert infer_polarity("我不喜欢什么题材") == "negative"
    assert infer_polarity("我关注哪些up主") == "positive"
    assert infer_polarity("我看了什么网页") == "any"


def test_infer_semantic_constraints_uses_central_pattern_specs() -> None:
    creator_constraints = infer_semantic_constraints("我用B站喜欢看哪些up主", answer_kind="creator")
    assert [(item.scope, item.facet, item.raw_value) for item in creator_constraints] == [
        ("interaction", "platform", "b站"),
    ]

    place_constraints = infer_semantic_constraints("我在杭州的时候喜欢去哪些咖啡馆", answer_kind="place")
    assert [(item.scope, item.facet, item.raw_value) for item in place_constraints] == [
        ("interaction", "located_in", "杭州"),
        ("target", "category", "咖啡馆"),
    ]


def test_extract_answer_object_mentions_prefers_answer_object_over_context_mentions() -> None:
    mentions = extract_answer_object_mentions("上次我看的主播他说的主题是什么")
    assert mentions == ["主题"]


def test_infer_answer_kind_uses_answer_object_mentions_first() -> None:
    assert infer_answer_kind("上次我看的主播他说的主题是什么") == "topic"


def test_extract_platform_constraint_prefers_interaction_scope() -> None:
    constraint = extract_platform_constraint("我用B站喜欢看哪些up主", answer_kind="creator")
    assert constraint is not None
    assert (constraint.scope, constraint.facet, constraint.raw_value) == ("interaction", "platform", "b站")


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


def test_extract_category_constraint_maps_known_place_categories() -> None:
    constraint = extract_category_constraint("我在杭州的时候喜欢去哪些咖啡馆")
    assert constraint is not None
    assert constraint.scope == "target"
    assert constraint.facet == "category"
    assert constraint.raw_value == "咖啡馆"
    assert constraint.resolved_facet_value == "coffee_shop"
