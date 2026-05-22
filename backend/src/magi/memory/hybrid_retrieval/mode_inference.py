"""Heuristic-only mode inference for queries that don't carry a caller-supplied
query_mode.

Phase 4: chat LLM no longer picks query_mode; it auto-detects via this module.
The Phase 3 IndexicalResolver still has authoritative override priority for
indexical queries (those are routed before this module runs).

Pure heuristic — no LLM call. Conservative default: exact_fact.
"""

from __future__ import annotations

import re
from typing import Optional


# CJK cues — substring match (no word-boundary concept needed)
_SUMMARY_CUES_CJK: tuple[str, ...] = (
    "总结", "概况", "汇总", "回顾", "概述",
)
_TEMPORAL_COMPARE_CUES_CJK: tuple[str, ...] = (
    "对比", "相比", "比较", "差别", "比起",
)
_CURRENT_STATE_CUES_CJK: tuple[str, ...] = (
    "现在", "目前", "最近", "这几天", "今天", "本周", "本月",
)

# English cues — word-boundary regex to avoid substring false-positives
# (e.g. 'now' inside 'known' / 'snow' / 'knowledge', 'vs' inside 'advise',
# 'recap' inside 'recapture'). Mirrors the Phase 2A evidence_routing.py
# pattern that explicitly fixed this bug class for browse⊂browser.
_SUMMARY_CUES_EN = re.compile(
    r"\b(summarize|summary|overview|recap|rundown)\b",
    re.IGNORECASE,
)
_TEMPORAL_COMPARE_CUES_EN = re.compile(
    r"\b(vs|compare|versus|difference)\b",
    re.IGNORECASE,
)
_CURRENT_STATE_CUES_EN = re.compile(
    r"\b(now|currently|lately|this\s+week|this\s+month)\b",
    re.IGNORECASE,
)


def _matches_summary(query: str) -> bool:
    if any(cue in query for cue in _SUMMARY_CUES_CJK):
        return True
    return bool(_SUMMARY_CUES_EN.search(query))


def _matches_temporal_compare(query: str) -> bool:
    if any(cue in query for cue in _TEMPORAL_COMPARE_CUES_CJK):
        return True
    return bool(_TEMPORAL_COMPARE_CUES_EN.search(query))


def _matches_current_state(query: str) -> bool:
    if any(cue in query for cue in _CURRENT_STATE_CUES_CJK):
        return True
    return bool(_CURRENT_STATE_CUES_EN.search(query))


def infer_query_mode(
    *,
    query: Optional[str],
    caller_hint: Optional[str],
) -> str:
    """Resolve the query_mode.

    Priority:
    1. caller_hint (if non-empty, trust it — backward compat for callers that
       explicitly set query_mode).
    2. Linguistic heuristics on the query body, in priority order:
       summary > temporal_compare > current_state.
    3. Default: exact_fact.
    """
    if caller_hint:
        return caller_hint
    if not query:
        return "exact_fact"
    if _matches_summary(query):
        return "summary"
    if _matches_temporal_compare(query):
        return "temporal_compare"
    if _matches_current_state(query):
        return "current_state"
    return "exact_fact"
