"""Research-request keyword classifiers used by planning heuristics.

These predicates are still consumed by ``planning_heuristics`` and the
``orchestration`` strategy resolver to bias *plan-time* decisions
(default leaf type, parallel mode, etc.). The earlier
``apply_research_guardrail`` post-processing step that mutated LLM
ContextDecisions has been removed — the LLM router's decision is
final and is not second-guessed by this module.
"""

from __future__ import annotations

import re


def is_complex_research_request(user_lower: str) -> bool:
    has_research_domain = any(
        kw in user_lower
        for kw in [
            "news",
            "新闻",
            "头条",
            "最新动态",
            "最近",
            "过去",
            "近",
            "资料",
            "信息汇总",
            "source",
            "来源",
            "link",
            "链接",
            "核实",
            "verify",
            "compare",
            "对比",
        ]
    )
    has_complex_constraint = any(
        kw in user_lower
        for kw in [
            "最近7天",
            "最近 7 天",
            "近7天",
            "过去7天",
            "最近一周",
            "近一周",
            "本月",
            "这个月",
            "top",
            "前",
            "条",
            "sources",
            "多来源",
            "交叉验证",
            "详情",
            "展开",
            "完整链接",
            "排序",
            "筛选",
        ]
    )
    return has_research_domain and has_complex_constraint


def should_decompose_external_request(user_lower: str) -> bool:
    """Return true when external evidence work deserves worker decomposition."""

    lowered = str(user_lower or "").lower()
    if is_complex_research_request(lowered):
        return True

    wants_source_breadth = any(
        kw in lowered
        for kw in [
            "citation",
            "citations",
            "source list",
            "multi-source",
            "cross-source",
            "sources",
            "links",
            "引用",
            "来源",
            "链接",
            "多来源",
            "交叉验证",
            "完整链接",
        ]
    )
    wants_research_work = any(
        kw in lowered
        for kw in [
            "research",
            "report",
            "survey",
            "verify",
            "compare",
            "调研",
            "报告",
            "汇总",
            "核实",
            "对比",
        ]
    )
    asks_for_many_items = bool(
        re.search(r"\b(?:top\s*)?\d{2,}\b", lowered)
        or re.search(r"(?:前|来|给我)\s*(?:十|[1-9]\d+)\s*(?:条|个|篇|项|家|处)", lowered)
    )
    return (wants_source_breadth and wants_research_work) or (
        wants_source_breadth and asks_for_many_items
    )


def needs_fetch_for_request(user_lower: str) -> bool:
    return any(
        kw in user_lower
        for kw in [
            "详情",
            "展开",
            "全文",
            "原文",
            "核实",
            "verify",
            "交叉验证",
            "具体看",
            "深挖",
        ]
    )


__all__ = [
    "is_complex_research_request",
    "needs_fetch_for_request",
    "should_decompose_external_request",
]
