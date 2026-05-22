"""Unit tests for heuristic query_mode inference.

Phase 4: chat LLM no longer picks query_mode; this module derives it from
query content + optional caller hint."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.mode_inference import infer_query_mode


def test_caller_hint_takes_priority():
    """When the caller explicitly passes a query_mode, trust it (backward compat)."""
    assert infer_query_mode(query="random text", caller_hint="exact_fact") == "exact_fact"
    assert infer_query_mode(query="总结一下", caller_hint="cross_session") == "cross_session"


def test_summary_cue_chinese():
    assert infer_query_mode(query="总结一下我最近的活动", caller_hint=None) == "summary"


def test_summary_cue_english():
    assert infer_query_mode(query="give me a summary of my week", caller_hint=None) == "summary"


def test_temporal_compare_cue():
    assert infer_query_mode(query="本月 vs 上月 我做了什么", caller_hint=None) == "temporal_compare"


def test_current_state_cue_chinese():
    assert infer_query_mode(query="我最近在听什么音乐", caller_hint=None) == "current_state"


def test_current_state_cue_english():
    assert infer_query_mode(query="what am I currently working on", caller_hint=None) == "current_state"


def test_no_cue_defaults_to_exact_fact():
    assert infer_query_mode(query="who is asuka", caller_hint=None) == "exact_fact"


def test_empty_query_defaults():
    assert infer_query_mode(query="", caller_hint=None) == "exact_fact"
    assert infer_query_mode(query=None, caller_hint=None) == "exact_fact"  # tolerate None


def test_summary_beats_current_state_when_both_match():
    """Summary cue ranks higher than current_state cue."""
    assert infer_query_mode(query="总结一下最近的事", caller_hint=None) == "summary"
