"""Pure heuristics used by chat task planning."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from ...orchestration import PlannedSubtask


def looks_like_external_evidence_subtask(description: str, subtask_prompt: str) -> bool:
    combined = f"{description}\n{subtask_prompt}".lower()
    return any(
        token in combined
        for token in [
            "web-search",
            "web search",
            "web-fetch",
            "external",
            "public source",
            "official doc",
            "official source",
            "public documentation",
            "article",
            "source",
            "link",
            "metro",
            "subway",
            "transit",
            "public transport",
            "restaurant",
            "dining",
            "itinerary",
            "attraction",
            "tourist",
            "opening hours",
            "reservation",
            "ticket",
            "weather",
            "hotel",
            "verify",
            "地铁",
            "公交",
            "交通",
            "换乘",
            "路线",
            "前往",
            "到达",
            "餐厅",
            "吃饭",
            "聚餐",
            "商圈",
            "景点",
            "行程",
            "游览",
            "开放时间",
            "预约",
            "门票",
            "天气",
            "酒店",
            "地址",
            "营业",
            "官网",
            "官方文档",
            "公开资料",
            "来源",
            "链接",
            "核实",
            "外部",
            "http://",
            "https://",
        ]
    )


def is_synthesis_only_subtask(description: str, subtask_prompt: str) -> bool:
    combined = f"{description}\n{subtask_prompt}".lower()
    has_synthesis_verb = any(
        token in combined
        for token in [
            "synthes",
            "aggregate",
            "combine",
            "merge",
            "final answer",
            "final response",
            "write the answer",
            "write the final",
            "summarize the results",
            "compare the findings",
            "compare the results",
            "汇总",
            "整合",
            "综合",
            "最终回答",
            "最终回复",
            "总结结果",
            "对比结果",
        ]
    )
    if not has_synthesis_verb:
        return False
    return any(
        token in combined
        for token in [
            "sibling",
            "other subtasks",
            "other subtask",
            "worker outputs",
            "worker results",
            "subtask outputs",
            "subtask results",
            "findings from",
            "results from",
            "previous tasks",
            "above results",
            "以上结果",
            "前面",
            "其他子任务",
            "worker",
        ]
    )


def looks_like_code_or_repo_request(user_message: str, subtask_prompt: str) -> bool:
    combined = f"{user_message}\n{subtask_prompt}".lower()
    return any(
        keyword in combined
        for keyword in [
            "architecture",
            "codebase",
            "repo",
            "backend",
            "frontend",
            "module",
            "code",
            "source",
            "file",
            "function",
            "class",
            "method",
            "implementation",
            "bug",
            "traceback",
            "runtime",
            "router",
            "src/",
            "backend/",
            "frontend/",
            "代码架构",
            "项目架构",
            "目录结构",
            "代码",
            "源码",
            "文件",
            "函数",
            "方法",
            "实现",
            "修复",
            "报错",
            "日志",
            "后端",
            "前端",
        ]
    )


def classify_request_profile(*, user_message: str, default_leaf_type: str) -> str:
    lowered = user_message.lower()
    if default_leaf_type == "CodeExplore" and any(
        keyword in lowered
        for keyword in [
            "architecture",
            "codebase",
            "repo",
            "代码架构",
            "项目架构",
            "代码库",
            "目录结构",
        ]
    ):
        return "repo_architecture"
    if is_complex_research_request(user_message):
        return "research"
    return "generic"


def is_complex_research_request(user_message: str) -> bool:
    lowered = user_message.lower()
    has_information_domain = any(
        keyword in lowered
        for keyword in [
            "news",
            "新闻",
            "头条",
            "消息",
            "最近",
            "过去",
            "近",
            "本月",
            "资料",
            "信息",
            "来源",
            "链接",
            "source",
            "link",
            "核实",
            "verify",
            "compare",
            "对比",
            "汇总",
        ]
    )
    has_complex_constraint = any(
        keyword in lowered
        for keyword in [
            "最近7天",
            "最近 7 天",
            "近7天",
            "过去7天",
            "最近一周",
            "近一周",
            "本月",
            "这个月",
            "给我",
            "条",
            "top",
            "链接",
            "来源",
            "详情",
            "展开",
            "核实",
            "verify",
            "交叉验证",
            "重要的",
        ]
    )
    return has_information_domain and has_complex_constraint


def needs_research_fetch(user_message: str) -> bool:
    lowered = user_message.lower()
    return any(
        keyword in lowered
        for keyword in [
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


def build_research_seed_subtasks(user_message: str) -> list[PlannedSubtask]:
    date_range_hint = extract_date_range_hint(user_message)
    date_suffix = ""
    if date_range_hint:
        date_suffix = f" Keep the work inside {date_range_hint['start_date']} to {date_range_hint['end_date']} (inclusive)."
    subtasks = [
        PlannedSubtask(
            description="Search official and local-source coverage",
            subagent_type="general-purpose",
            prompt=(
                "Search official, government, and local-source coverage that matches the user's request."
                " Collect the strongest candidate items with title, date, source, link, and a short summary."
                f"{date_suffix}"
            ),
            parallel_group="group_a",
        ),
        PlannedSubtask(
            description="Search major media and commercial-source coverage",
            subagent_type="general-purpose",
            prompt=(
                "Search major media, commercial, or independent sources that match the user's request."
                " Collect the strongest candidate items with title, date, source, link, and a short summary."
                f"{date_suffix}"
            ),
            parallel_group="group_a",
        ),
    ]
    if needs_research_fetch(user_message):
        subtasks.append(
            PlannedSubtask(
                description="Fetch and verify article details",
                subagent_type="general-purpose",
                prompt=(
                    "For the most important candidate items, fetch article pages as needed to verify dates,"
                    " titles, links, and summaries before the parent task aggregates the answer."
                    f"{date_suffix}"
                ),
                parallel_group="group_b",
            )
        )
    return subtasks


def extract_date_range_hint(user_message: str) -> Optional[dict[str, str]]:
    lowered = user_message.lower()
    today = datetime.now().date()

    relative_days_match = re.search(r"(最近|过去|近)\s*(\d+)\s*天", user_message)
    if relative_days_match:
        days = max(1, int(relative_days_match.group(2)))
        start_date = today - timedelta(days=days - 1)
        return {"start_date": start_date.isoformat(), "end_date": today.isoformat()}

    if any(token in lowered for token in ["最近一周", "近一周", "过去一周", "last week"]):
        start_date = today - timedelta(days=6)
        return {"start_date": start_date.isoformat(), "end_date": today.isoformat()}

    if any(token in lowered for token in ["本月", "这个月", "this month"]):
        start_date = today.replace(day=1)
        return {"start_date": start_date.isoformat(), "end_date": today.isoformat()}

    if any(token in lowered for token in ["本周", "这周", "this week"]):
        start_date = today - timedelta(days=today.weekday())
        return {"start_date": start_date.isoformat(), "end_date": today.isoformat()}

    return None
