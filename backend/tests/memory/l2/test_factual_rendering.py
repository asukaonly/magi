"""Fact wording must retain the typed temporal qualifiers."""

import pytest

from magi.memory.l2.factual_rendering import render_grounded_fact
from magi.memory.l2.phase1_models import L2Phase1FactClaim


@pytest.mark.parametrize(
    ("cue", "zh", "en"),
    [
        ("recent", "用户最近喜欢苹果。", "The user recently likes 苹果."),
        ("one_off", "用户曾在一次经历中喜欢苹果。", "The user on one occasion likes 苹果."),
        ("unspecified", "用户喜欢苹果。", "The user likes 苹果."),
    ],
)
def test_fact_renderer_retains_temporal_qualifier(cue: str, zh: str, en: str) -> None:
    claim = L2Phase1FactClaim(predicate="LIKES", object_ref="苹果", temporal_cue=cue)
    assert render_grounded_fact(claim, language="zh-CN") == zh
    assert render_grounded_fact(claim, language="en") == en
