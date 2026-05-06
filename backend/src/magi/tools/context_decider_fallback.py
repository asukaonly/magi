"""Rule-based fallback routing for ContextDecider."""

from __future__ import annotations

import logging
from typing import Any, Optional

from .context_routing import ContextDecision
from ..config.models import ThinkingDepth

logger = logging.getLogger(__name__)


class ContextDeciderFallbackMixin:
    """Fallback tool selection used when LLM routing fails."""

    max_tools: int
    tool_registry: Any

    def _default_orchestration_strategy(self, tools: list[str] | None = None, user_lower: str = "") -> dict[str, Any]: ...

    def _is_complex_research_request(self, user_lower: str) -> bool: ...

    def _needs_fetch_for_request(self, user_lower: str) -> bool: ...

    def _rule_based_fallback(
        self,
        user_message: str,
        context: Optional[dict[str, Any]] = None,
    ) -> ContextDecision:
        """
        Rule-based tool selection as fallback when LLM fails

        Simple keyword matching to determine which tools might be needed
        """
        user_lower = user_message.lower()
        tools = []
        intent = "chat"
        available_tools = self.tool_registry.list_tools()

        retry_keywords = [
            "再查",
            "再试",
            "重试",
            "再来一次",
            "再来一遍",
            "retry",
            "again",
        ]
        if any(kw in user_lower for kw in retry_keywords) and context:
            recent_tool_errors = context.get("recent_tool_errors")
            if isinstance(recent_tool_errors, list) and recent_tool_errors:
                last_tool = str(recent_tool_errors[0].get("tool_name", "")).strip()
                if last_tool and last_tool in available_tools:
                    logger.info(f"[ContextDecider] Retry fallback matched last failed tool: {last_tool}")
                    return ContextDecision(
                        intent="retry_last_tool",
                        tools=[last_tool],
                        thinking_depth=ThinkingDepth.NONE,
                        reasoning=f"Retry request detected, reusing last failed tool: {last_tool}",
                        orchestration_strategy=self._default_orchestration_strategy(),
                    )

        trace_keywords = [
            "参数",
            "耗时",
            "tool",
            "工具",
            "调用",
            "trace",
            "duration",
            "latency",
            "为什么失败",
            "failed",
            "error code",
        ]
        if "trace_query" in available_tools and any(kw in user_lower for kw in trace_keywords):
            recent_tool_state = context.get("recent_tool_state") if context else None
            if isinstance(recent_tool_state, list) and recent_tool_state:
                logger.info("[ContextDecider] Trace detail fallback matched recent tool state")
                return ContextDecision(
                    intent="chat",
                    tools=["trace_query"],
                    thinking_depth=ThinkingDepth.NONE,
                    reasoning="The user is asking for concrete recent tool execution details, so query the persisted trace.",
                    orchestration_strategy=self._default_orchestration_strategy(),
                )

        complex_keywords = [
            "复杂",
            "multi-step",
            "multi step",
            "分步",
            "规划",
            "方案",
            "架构",
            "refactor",
            "migration",
            "codebase",
            "repo",
        ]
        if "agent" in available_tools and any(kw in user_lower for kw in complex_keywords):
            strategy = self._default_orchestration_strategy(["agent"], user_lower)
            return ContextDecision(
                intent="planning",
                tools=["agent"],
                thinking_depth=ThinkingDepth.HIGH,
                reasoning="Complex request detected, delegating to worker agent tool",
                orchestration_strategy=strategy,
            )

        if self._is_complex_research_request(user_lower):
            tools = []
            if "web-search" in available_tools:
                tools.append("web-search")
            if self._needs_fetch_for_request(user_lower) and "web-fetch" in available_tools:
                tools.append("web-fetch")
            if not tools and "bash" in available_tools:
                tools.append("bash")
            return ContextDecision(
                intent="planning",
                tools=tools[: self.max_tools],
                thinking_depth=ThinkingDepth.HIGH,
                reasoning="Complex research request detected, routing to generic parent-task decomposition.",
                orchestration_strategy=self._default_orchestration_strategy(tools[: self.max_tools], user_lower),
            )

        if any(
            kw in user_lower
            for kw in [
                "抓网页",
                "抓取网页",
                "提取网页",
                "网页内容",
                "fetch网页",
                "web fetch",
                "web-fetch",
                "url内容",
                "读取网页",
            ]
        ) or "http://" in user_lower or "https://" in user_lower:
            if "web-fetch" in available_tools:
                tools.append("web-fetch")
                intent = "web_interaction"

        if any(kw in user_lower for kw in ["天气", "weather", "气温", "temperature", "news", "新闻", "股票", "stock", "汇率", "exchange rate"]):
            if any(kw in user_lower for kw in ["天气", "weather", "气温", "temperature"]) and "weather" in available_tools:
                tools.append("weather")
            elif "web-search" in available_tools:
                tools.append("web-search")
            else:
                tools.append("bash")
            intent = "realtime_query"

        if any(kw in user_lower for kw in ["读取file", "read file", "查看file", "打开file", "fileContent"]):
            tools.append("file_read")
            intent = "file_read"
        if any(kw in user_lower for kw in ["写入file", "write file", "savefile", "createfile"]):
            tools.append("file_write")
            intent = "file_write"

        if any(kw in user_lower for kw in ["Executecommand", "runcommand", "bash", "shell", "commandrow"]):
            tools.append("bash")
            intent = "command_execution"

        if any(kw in user_lower for kw in ["截图", "screenshot", "网页", "website", "浏览器"]):
            if "截图" in user_lower or "screenshot" in user_lower:
                tools.append("bash")
            intent = "web_interaction"

        for skill_name in self.tool_registry._skills.keys():
            if f"/{skill_name}" in user_message or skill_name in user_lower:
                tools.append(f"/{skill_name}")
                intent = f"skill_{skill_name}"
                break

        logger.info(f"[ContextDecider] Rule-based fallback | Intent: {intent} | Tools: {tools}")

        return ContextDecision(
            intent=intent,
            tools=tools[:self.max_tools],
            thinking_depth=ThinkingDepth.NONE,
            reasoning="Rule-based fallback (LLM returned empty/incomplete response)",
            orchestration_strategy=self._default_orchestration_strategy(tools[:self.max_tools], user_lower),
        )


__all__ = ["ContextDeciderFallbackMixin"]
