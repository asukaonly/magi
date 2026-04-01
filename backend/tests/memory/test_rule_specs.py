"""Tests for hybrid retrieval rule specs."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.rule_specs import (
    extract_location_constraint,
    infer_source_domain_filters,
    infer_answer_shape,
    infer_polarity,
    infer_semantic_constraints,
)


def test_infer_answer_shape_uses_central_query_specs() -> None:
    assert infer_answer_shape("我喜欢什么题材") == "list"
    assert infer_answer_shape("我喜欢B站吗") == "boolean"
    assert infer_answer_shape("上次我看的主播他说的主题是什么") == "list"
    assert infer_answer_shape("我最喜欢的up主") == "single"


def test_infer_answer_shape_excludes_why_from_list() -> None:
    assert infer_answer_shape("为什么这个不行") == "single"
    assert infer_answer_shape("你为什么喜欢猫") == "single"
    # "什么" without "为" still triggers list
    assert infer_answer_shape("你喜欢什么") == "list"


def test_infer_polarity_uses_central_keyword_specs() -> None:
    assert infer_polarity("我不喜欢什么题材") == "negative"
    assert infer_polarity("我关注哪些up主") == "positive"
    assert infer_polarity("我看了什么网页") == "any"


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
