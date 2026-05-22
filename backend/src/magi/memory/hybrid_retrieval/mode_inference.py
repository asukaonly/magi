"""Heuristic-only mode inference for queries that don't carry a caller-supplied
query_mode.

Phase 4: chat LLM no longer picks query_mode; it auto-detects via this module.
The Phase 3 IndexicalResolver still has authoritative override priority for
indexical queries (those are routed before this module runs).

Pure heuristic — no LLM call. Conservative default: exact_fact.
"""

from __future__ import annotations

from typing import Optional


_SUMMARY_CUES: tuple[str, ...] = (
    "总结", "概况", "汇总", "回顾", "概述",
    "summarize", "summary", "overview", "recap", "rundown",
)

_TEMPORAL_COMPARE_CUES: tuple[str, ...] = (
    "vs", "对比", "比较", "差别", "比起",
    "compare", "versus", "difference",
)

_CURRENT_STATE_CUES: tuple[str, ...] = (
    "现在", "目前", "最近", "这几天", "今天", "本周", "本月",
    "now", "currently", "lately", "this week", "this month",
)


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
    lowered = query.lower()
    if any(cue in query or cue in lowered for cue in _SUMMARY_CUES):
        return "summary"
    if any(cue in query or cue in lowered for cue in _TEMPORAL_COMPARE_CUES):
        return "temporal_compare"
    if any(cue in query or cue in lowered for cue in _CURRENT_STATE_CUES):
        return "current_state"
    return "exact_fact"
