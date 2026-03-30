"""Tests for hybrid retrieval rule specs."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.rule_specs import (
    infer_answer_kind,
    infer_answer_shape,
    infer_polarity,
    infer_semantic_constraints,
)


def test_infer_answer_kind_uses_central_keyword_specs() -> None:
    assert infer_answer_kind("我喜欢哪些频道") == "creator"
    assert infer_answer_kind("我喜欢什么题材") == "topic"
    assert infer_answer_kind("我喜欢B站吗") == "software"


def test_infer_answer_shape_uses_central_query_specs() -> None:
    assert infer_answer_shape("我喜欢什么题材") == "list"
    assert infer_answer_shape("我喜欢B站吗") == "boolean"
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
