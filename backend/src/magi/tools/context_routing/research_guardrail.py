"""Research-request keyword classifiers used by planning heuristics.

These predicates are still consumed by ``planning_heuristics`` and the
``orchestration`` strategy resolver to bias *plan-time* decisions
(default leaf type, parallel mode, etc.). The earlier
``apply_research_guardrail`` post-processing step that mutated LLM
ContextDecisions has been removed — the LLM router's decision is
final and is not second-guessed by this module.
"""

from __future__ import annotations


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
]
