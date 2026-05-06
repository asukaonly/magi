"""Research-request guardrails for context routing."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .models import ContextDecision
from ...config.models import ThinkingDepth


def is_bounded_advice_request(user_lower: str) -> bool:
    has_choice_or_advice = any(
        kw in user_lower
        for kw in [
            "推荐",
            "怎么选",
            "如何选",
            "选购",
            "买什么",
            "购买",
            "预算",
            "适合",
            "对比",
            "recommend",
            "recommendation",
            "which",
            "choose",
            "buy",
            "budget",
            "compare",
        ]
    )
    if not has_choice_or_advice:
        return False

    code_or_workspace_scope = any(
        kw in user_lower
        for kw in [
            "codebase",
            "repo",
            "repository",
            "src/",
            "backend/",
            "frontend/",
            "代码库",
            "代码结构",
            "架构",
            "实现",
            "源码",
        ]
    )
    if code_or_workspace_scope:
        return False

    fresh_or_evidence_requirement = any(
        kw in user_lower
        for kw in [
            "news",
            "新闻",
            "最新",
            "实时",
            "今天",
            "本周",
            "最近7天",
            "最近 7 天",
            "近7天",
            "过去7天",
            "当前价格",
            "报价",
            "库存",
            "链接",
            "来源",
            "引用",
            "官网",
            "source",
            "sources",
            "link",
            "links",
            "cite",
            "citation",
            "current price",
            "latest",
            "real-time",
            "multi-source",
            "多来源",
            "交叉验证",
        ]
    )
    return not fresh_or_evidence_requirement


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
    if is_bounded_advice_request(user_lower):
        selected_tools = [tool for tool in decision.tools if tool != "agent"][:max_tools]
        decision.tools = selected_tools
        if decision.intent == "planning":
            decision.intent = "chat"
        decision.orchestration_strategy = strategy_factory(selected_tools, user_lower)
        if decision.orchestration_strategy.get("mode") == "decompose":
            decision.orchestration_strategy = {
                "mode": "direct",
                "planner": "task_agent",
                "default_leaf_type": "general-purpose",
                "allow_parallel": False,
            }
        decision.reasoning = (
            f"{decision.reasoning} Bounded advice guardrail: keep recommendation "
            "or comparison turns in the main chat path unless the user asks for "
            "fresh, linked, or multi-source evidence."
        ).strip()
        return decision
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
    "is_bounded_advice_request",
    "is_complex_research_request",
    "needs_fetch_for_request",
]
