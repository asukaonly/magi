"""Research-request guardrails for context routing."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .models import ContextDecision
from ...config.models import ThinkingDepth


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


def apply_research_guardrail(
    *,
    user_message: str,
    decision: ContextDecision,
    available_tools: list[dict[str, Any]],
    max_tools: int,
    strategy_factory: Callable[[Optional[list[str]], str], dict[str, Any]],
) -> ContextDecision:
    user_lower = user_message.lower()
    if not is_complex_research_request(user_lower):
        return decision
    available_names = {str(item.get("name", "")).strip() for item in available_tools}
    tools: list[str] = []
    if "web-search" in available_names:
        tools.append("web-search")
    if needs_fetch_for_request(user_lower) and "web-fetch" in available_names:
        tools.append("web-fetch")
    if not tools and "bash" in available_names:
        tools.append("bash")
    selected_tools = tools[:max_tools]
    return ContextDecision(
        intent="planning",
        tools=selected_tools,
        thinking_depth=ThinkingDepth.HIGH,
        reasoning="Complex research request guardrail: force bounded generic decomposition with explicit retrieval steps.",
        orchestration_strategy=strategy_factory(selected_tools, user_lower),
    )


__all__ = [
    "apply_research_guardrail",
    "is_complex_research_request",
    "needs_fetch_for_request",
]