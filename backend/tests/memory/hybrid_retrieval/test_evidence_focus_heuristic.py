"""Linguistic heuristic for evidence_focus, used by RuleBasedIntentDecider and
service_plan_augmentation when no LLM refinement is available."""

import pytest

from magi.memory.hybrid_retrieval.evidence_routing import (
    infer_evidence_focus_heuristic,
)


def test_observed_cue_browsed_chinese():
    assert infer_evidence_focus_heuristic("我浏览过哪些公司") == "observed"


def test_observed_cue_visited_english():
    assert infer_evidence_focus_heuristic("which websites did I visit") == "observed"


def test_declared_cue_liked_chinese():
    assert infer_evidence_focus_heuristic("我喜欢什么音乐") == "declared"


def test_declared_cue_told_english():
    assert infer_evidence_focus_heuristic("what did I tell you my name was") == "declared"


def test_mixed_cues_return_both():
    assert (
        infer_evidence_focus_heuristic("我浏览过的公司里我说过喜欢的")
        == "both"
    )


def test_no_cues_returns_none():
    assert infer_evidence_focus_heuristic("天气怎么样") is None
    assert infer_evidence_focus_heuristic("about me") is None
