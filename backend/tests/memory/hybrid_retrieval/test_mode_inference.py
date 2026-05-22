"""Unit tests for heuristic query_mode inference.

Phase 4: chat LLM no longer picks query_mode; this module derives it from
query content.

Round 5 #9: the `caller_hint` parameter was removed — callers with an
explicit query_mode short-circuit at `service.py` and never reach the
inference module."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.mode_inference import infer_query_mode


def test_summary_cue_chinese():
    assert infer_query_mode(query="总结一下我最近的活动") == "summary"


def test_summary_cue_english():
    assert infer_query_mode(query="give me a summary of my week") == "summary"


def test_temporal_compare_cue():
    assert infer_query_mode(query="本月 vs 上月 我做了什么") == "temporal_compare"


def test_temporal_compare_cue_chinese_xiangbi():
    """Round 5 #11: 相比 is a temporal_compare cue alongside 对比."""
    assert infer_query_mode(query="本月相比上月有什么变化") == "temporal_compare"


def test_current_state_cue_chinese():
    assert infer_query_mode(query="我最近在听什么音乐") == "current_state"


def test_current_state_cue_english():
    assert infer_query_mode(query="what am I currently working on") == "current_state"


def test_no_cue_defaults_to_exact_fact():
    assert infer_query_mode(query="who is asuka") == "exact_fact"


def test_empty_query_defaults():
    assert infer_query_mode(query="") == "exact_fact"
    assert infer_query_mode(query=None) == "exact_fact"  # tolerate None


def test_summary_beats_current_state_when_both_match():
    """Summary cue ranks higher than current_state cue."""
    assert infer_query_mode(query="总结一下最近的事") == "summary"


# Regression: word-boundary tests (Phase 4 post-review fix)

def test_now_does_not_match_inside_known():
    """'now' is a CURRENT_STATE cue but must not match inside 'known'."""
    assert infer_query_mode(query="what do you think I know about this") == "exact_fact"


def test_now_does_not_match_inside_knowledge():
    assert infer_query_mode(query="my knowledge of python") == "exact_fact"


def test_now_does_not_match_inside_snow():
    assert infer_query_mode(query="how much snow last winter") == "exact_fact"


def test_vs_does_not_match_inside_advise():
    """'vs' is a TEMPORAL_COMPARE cue but must not match inside 'advise'."""
    assert infer_query_mode(query="what do you advise") == "exact_fact"


def test_vs_does_not_match_inside_obvious():
    assert infer_query_mode(query="what's the obvious answer") == "exact_fact"


def test_recap_does_not_match_inside_recapture():
    """'recap' is a SUMMARY cue but must not match inside 'recapture'."""
    assert infer_query_mode(query="how do I recapture my username") == "exact_fact"


def test_overview_still_matches_summary():
    """Word boundary fix must not break legitimate matches."""
    assert infer_query_mode(query="give me an overview") == "summary"


def test_now_at_word_boundary_still_matches():
    """'right now' must still trigger current_state."""
    assert infer_query_mode(query="what am I doing right now") == "current_state"


def test_compare_still_matches_temporal_compare():
    """'compare' is a temporal_compare cue with safe word boundaries."""
    assert infer_query_mode(query="compare my browsing vs my downloads") == "temporal_compare"
