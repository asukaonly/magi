"""
Context Decider - LLM-powered context and tool selection

Decides:
1. User intent classification
2. Top 5 most relevant tools for the current request
3. Memory layer to retrieve (TODO)

This replaces the old ToolSelector for better tool selection.
"""
import json
import logging
from typing import Dict, Any, Optional, List

from ..config.models import LLMScenario, ThinkingDepth
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..config.constants import DEFAULT_MAX_TOKENS, DEFAULT_THINKING_TOKENS
from .registry import ToolRegistry
from .context_decider_context import ContextDeciderContext
from .context_decider_prompt import build_context_decider_prompt
from .context_routing import (
    MEMORY_RETRIEVAL_TRIGGERS,
    ContextDecision,
    MemoryGuidance,
    apply_memory_guidance,
    apply_research_guardrail,
    default_orchestration_strategy,
    evaluate_memory_need,
    is_complex_research_request,
    needs_fetch_for_request,
    normalize_orchestration_strategy,
)
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger('context_decider')


class ContextDecider:
    """
    Context Decision Module

    Analyzes user request and selects the most relevant tools.
    Uses LLM to understand intent and match with available tools.
    """

    system_PROMPT = """You are a Context Decider, the intelligent router of an autonomous agent system.
Your SOLE function is to analyze the user's request and output a precise JSON configuration.

### 1. Response Format
Respond with a SINGLE valid JSON object. No markdown formatting, not explanations.

JSON structure:
{
  "intent": "string",
  "tools": ["string"],
  "thinking_depth": "none|low|medium|high|max",
  "reasoning": "string",
  "orchestration_strategy": {
    "mode": "direct|decompose",
    "planner": "task_agent|plan_worker",
    "default_leaf_type": "Explore|general-purpose",
    "allow_parallel": boolean
  }
}

### 2. Intent Categories
- realtime_query: Weather, stocks, news, current events
- web_interaction: Navigating websites, filling forms
- code_execution: Writing, debugging, analyzing code
- file_operation: Reading, writing, listing files
- chat: Casual conversation, greetings, simple Q&A
- planning: Complex multi-step tasks

### 3. Tool vs Skill Selection
- Tools: Basic operations (file read/write, bash commands)
- Skills: Complex capabilities with specialized knowledge (start with /)
- Agent tool (`agent`): Launch specialized worker agents for complex multi-step work.

**Prioritize Skills when:**
- Task requires specialized knowledge or workflows
- User request matches a skill's description
- External resources or web access needed

**Use Tools when:**
- Simple file operations (read/write/list/edit) for text files.
- For binary files (images, PDFs, etc.) modification, use bash to call appropriate processing tools, DO NOT use file_read/file_write alone.
- Command execution
- No specialized knowledge needed

**Use `agent` tool proactively when:**
- The task is complex and likely needs many search/verification steps.
- You are not confident one or two direct tool calls can finish it.
- You need parent-task decomposition into bounded worker subtasks.

Always check the "Available Skills" section below for skill descriptions and match user requests accordingly.

Questions about the user's stored user preferences, personal facts, prior stated likes/dislikes, or customized settings should prefer `memory_query` when that tool is available.

### 4. Thinking Depth (reasoning effort)
Select the thinking depth based on task complexity:

"thinking_depth": "none" — No extended reasoning needed:
- Casual chat, greetings, simple Q&A
- Information queries (weather, time, stock prices)
- Executing explicit instructions (user provided exact steps)
- Simple CRUD operations

"thinking_depth": "low" — Light reasoning:
- Single file read/write
- Straightforward tool use with clear parameters
- Simple factual lookups requiring minor judgment

"thinking_depth": "medium" — Moderate reasoning:
- Multi-step tasks (2-3 steps) with clear structure
- Code modifications within a single file
- Creative writing or roleplay scenarios
- Debugging with known symptoms

"thinking_depth": "high" — Deep reasoning:
- Architecture design or multi-file refactoring
- Complex bug diagnosis requiring reasoning chains
- Multi-step planning (more than 3 steps)
- Code review with modification suggestions

"thinking_depth": "max" — Maximum reasoning budget:
- Novel algorithm design or complex mathematical proofs
- Large-scale system re-architecture
- Extremely ambiguous or open-ended research tasks

### 5. Few-Shot Examples

User: "hey"
JSON: {"intent": "chat", "tools": [], "thinking_depth": "none", "reasoning": "Casual greeting.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "what's the weather in tokyo"
JSON: {"intent": "realtime_query", "tools": ["weather"], "thinking_depth": "none", "reasoning": "Real-time weather query. Use the dedicated weather tool.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "read /src/main.py and fix the race condition"
JSON: {"intent": "code_execution", "tools": ["file_read", "file_write"], "thinking_depth": "high", "reasoning": "Complex bug diagnosis required.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "analyze this large repo and design a migration plan"
JSON: {"intent": "planning", "tools": ["agent"], "thinking_depth": "high", "reasoning": "Large repo analysis should be decomposed by the parent task agent into bounded workers.", "orchestration_strategy": {"mode": "decompose", "planner": "task_agent", "default_leaf_type": "Explore", "allow_parallel": true}}

User: "find the 10 most important Hangzhou news stories from the last 7 days and give me links"
JSON: {"intent": "planning", "tools": ["web-search", "web-fetch"], "thinking_depth": "medium", "reasoning": "This is a bounded multi-source research request with a time window, result count, and source requirements, so it should be decomposed into generic research workers.", "orchestration_strategy": {"mode": "decompose", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": true}}

User: "convert ~/tmp/logo.png to transparent background"
JSON: {"intent": "file_operation", "tools": ["bash"], "thinking_depth": "low", "reasoning": "Processing a binary image file requires external tools like ImageMagick, which must be executed via bash. Standard file_read/write cannot modify image contents.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "我喜欢什么天气"
JSON: {"intent": "chat", "tools": ["memory_query"], "thinking_depth": "none", "reasoning": "The user is asking about a stored personal preference, so memory recall is needed.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "我的默认工作目录是什么"
JSON: {"intent": "chat", "tools": ["memory_query"], "thinking_depth": "none", "reasoning": "The user is asking about a stored personalized setting or profile fact, so memory recall is needed.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "按之前那套流程修一下这个 bug"
JSON: {"intent": "code_execution", "tools": ["file_read", "file_write"], "thinking_depth": "medium", "reasoning": "This is a workflow reuse request, not an explicit historical recall request.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "2022年9月我在哪里拍了照片"
JSON: {"intent": "chat", "tools": ["memory_query"], "thinking_depth": "low", "reasoning": "This asks for historical asset recall. Use memory_query first for the factual answer, and only add source-specific asset tools when the user needs concrete files.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "把刚才那些照片发出来"
JSON: {"intent": "chat", "tools": ["photo_library_resolve_photo_refs", "prepare_chat_attachments"], "thinking_depth": "low", "reasoning": "The user wants to send previously identified assets, so use the source resolver to obtain file paths and then prepare chat attachments.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "刚刚你调了什么工具，参数和耗时是多少"
JSON: {"intent": "chat", "tools": ["trace_query"], "thinking_depth": "low", "reasoning": "The user is asking for exact recent execution details, so query the persisted execution trace instead of relying on conversational memory.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

Note: Always match tools/skills from the "Available Tools" and "Available Skills" lists. If not matching skill exists, use basic tools."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: Optional[LLMAdapter] = None,
        llm_pool=None,
        max_tools: int = 5,
    ):
        """
        initialize the Context Decider

        Args:
            tool_registry: Tool registry instance
            llm_adapter: LLM adapter for analysis
            max_tools: Maximum number of tools to select
        """
        self.tool_registry = tool_registry
        self._llm_pool = llm_pool
        self.llm = llm_adapter or self._resolve_llm_from_pool()
        self.provider_bridge = LLMProviderBridge(self.llm) if self.llm else None
        self.max_tools = max_tools

    def _resolve_llm_from_pool(self) -> Optional[LLMAdapter]:
        if self._llm_pool is None:
            return None
        return self._llm_pool.get(LLMScenario.CONTEXT_DECIDER)

    async def decide(
        self,
        user_message: str,
        context: Optional[ContextDeciderContext] = None,
    ) -> ContextDecision:
        """
        Analyze user request and decide on tools

        Args:
            user_message: User's message
            context: additional context (environment info, etc.)

        Returns:
            ContextDecision with selected tools
        """
        pooled_llm = self._resolve_llm_from_pool()
        if pooled_llm is not None and pooled_llm is not self.llm:
            self.llm = pooled_llm
            self.provider_bridge = LLMProviderBridge(pooled_llm)

        if not self.llm:
            logger.warning("[ContextDecider] LLM not available")
            return ContextDecision(
                intent="unknown",
                tools=[],
                deep_thinking=False,
                reasoning="LLM not available",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

        # Get available tools
        available_tools = self._get_available_tools()

        # Build the prompt
        user_prompt = self._build_prompt(user_message, available_tools, context)

        try:
            # Call LLM
            import time
            import uuid

            request_id = str(uuid.uuid4())[:8]
            start_time = time.time()

            log_llm_request(
                llm_logger,
                request_id=request_id,
                model=self.llm.model_name,
                system_prompt=self.system_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            provider_response = await self.provider_bridge.chat_response(
                system_prompt=self.system_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=DEFAULT_THINKING_TOKENS,
                temperature=0.3,
                # ContextDecider is a fast router and should not enter reasoning mode.
                disable_thinking=True,
                event_context={
                    "request_id": request_id,
                    "request_kind": "context_decider",
                    "agent_id": "context_decider",
                },
            )
            response = provider_response.content

            # Check if response is empty or incomplete
            if not response or not response.strip():
                logger.warning("[ContextDecider] LLM returned empty response, using rule-based fallback")
                return self._rule_based_fallback(user_message, context)

            # Check for incomplete JSON response (just "{" or similar)
            stripped = response.strip()
            if stripped in ("{", "}", "{}"):
                logger.warning(f"[ContextDecider] LLM returned incomplete response: {stripped}, using rule-based fallback")
                return self._rule_based_fallback(user_message, context)

            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=response,
                success=True,
                duration_ms=duration_ms,
            )

            # Parse response
            decision = self._parse_response(response)
            decision = self._apply_research_guardrail(
                user_message=user_message,
                decision=decision,
                available_tools=available_tools,
            )
            decision = self._apply_memory_guidance(
                user_message=user_message,
                context=context,
                decision=decision,
                available_tools=available_tools,
            )
            decision.llm_trace = self._build_llm_trace(
                metadata=provider_response.metadata,
                disable_thinking=True,
                duration_ms=duration_ms,
            )

            logger.info(
                f"[ContextDecider] Decision made | Intent: {decision.intent} | "
                f"Tools: {decision.tools} | Thinking: {decision.thinking_depth.value} | Reasoning: {decision.reasoning}"
            )
            logger.debug(f"[ContextDecider] Raw LLM response: {response[:500]}")

            return decision

        except Exception as e:
            logger.error(f"[ContextDecider] Decision failed: {e}")
            return ContextDecision(
                intent="error",
                tools=[],
                deep_thinking=False,
                reasoning=f"error: {str(e)}",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

    def _build_llm_trace(
        self,
        *,
        metadata: Optional[Dict[str, Any]],
        disable_thinking: bool,
        duration_ms: int,
    ) -> Dict[str, Any]:
        trace_metrics = dict((metadata or {}).get("trace_metrics") or {})
        trace_metrics.setdefault("provider", getattr(self.llm, "provider_name", "unknown"))
        trace_metrics.setdefault("model", str(getattr(self.llm, "model_name", "unknown")))
        trace_metrics.setdefault("input_tokens", 0)
        trace_metrics.setdefault("output_tokens", 0)
        trace_metrics.setdefault("total_tokens", 0)
        trace_metrics.setdefault("reasoning_tokens", 0)
        trace_metrics.setdefault("cache_read_tokens", 0)
        trace_metrics.setdefault("cache_write_tokens", 0)
        trace_metrics.setdefault("thinking_enabled", not disable_thinking)
        trace_metrics.setdefault("duration_ms", duration_ms)
        return trace_metrics

    def _get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools with metadata"""
        tools_info = self.tool_registry.get_all_tools_info()
        return [
            {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "type": tool.get("type", "tool"),
            }
            for tool in tools_info
            if tool.get("type") != "skill"  # Skills are handled separately
        ]

    def _build_prompt(
        self,
        user_message: str,
        available_tools: List[Dict[str, Any]],
        context: Optional[ContextDeciderContext],
    ) -> str:
        """Build the prompt for context decision"""
        return build_context_decider_prompt(
            tool_registry=self.tool_registry,
            user_message=user_message,
            available_tools=available_tools,
            context=context,
        )

    def _parse_response(self, response: str) -> ContextDecision:
        """Parse LLM response into ContextDecision"""
        import re

        response = response.strip()

        # Handle empty response
        if not response:
            logger.warning("[ContextDecider] Empty LLM response")
            return ContextDecision(
                intent="unknown",
                tools=[],
                deep_thinking=False,
                reasoning="Empty LLM response",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

        # Handle incomplete response (just `{` or similar)
        if response == "{" or response == "{}":
            logger.warning(f"[ContextDecider] Incomplete LLM response: {response}")
            return ContextDecision(
                intent="unknown",
                tools=[],
                deep_thinking=False,
                reasoning="Incomplete LLM response",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

        # Try to extract JSON - multiple patterns
        # pattern 1: Standard nested JSON
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)

        # pattern 2: If pattern 1 fails, try to find any JSON-like structure
        if not json_match:
            # Try to find JSON that starts with { and ends with }
            json_match = re.search(r'\{.*\}', response, re.DOTALL)

        if json_match:
            try:
                json_str = json_match.group()
                data = json.loads(json_str)

                # Validate required fields
                if not isinstance(data, dict):
                    raise ValueError("Response is not a JSON object")

                intent = data.get("intent", "unknown")
                tools = data.get("tools", [])
                reasoning = data.get("reasoning", "")
                orchestration_strategy = self._normalize_orchestration_strategy(
                    data.get("orchestration_strategy")
                )

                # Parse thinking_depth (new) or fall back to legacy deep_thinking bool
                raw_depth = data.get("thinking_depth")
                thinking_depth: ThinkingDepth | None = None
                if isinstance(raw_depth, str):
                    try:
                        thinking_depth = ThinkingDepth(raw_depth.lower())
                    except ValueError:
                        pass
                if thinking_depth is None:
                    # Legacy fallback
                    deep_thinking = data.get("deep_thinking", False)
                    thinking_depth = ThinkingDepth.HIGH if deep_thinking else ThinkingDepth.NONE

                # Validate tools are available
                valid_tools = []
                available = {t["name"] for t in self._get_available_tools()}
                for tool in tools[:self.max_tools]:
                    if tool in available:
                        valid_tools.append(tool)
                    elif tool.startswith("/") and self.tool_registry.is_skill(tool.lstrip("/")):
                        valid_tools.append(tool)

                return ContextDecision(
                    intent=intent,
                    tools=valid_tools,
                    thinking_depth=thinking_depth,
                    reasoning=reasoning,
                    orchestration_strategy=orchestration_strategy,
                )
            except json.JSONDecodeError as e:
                logger.warning(f"[ContextDecider] JSON decode error: {e}")
            except ValueError as e:
                logger.warning(f"[ContextDecider] Invalid response structure: {e}")

        # Fallback: no tools selected
        logger.warning(f"[ContextDecider] Failed to parse response: {response[:200]}")
        return ContextDecision(
            intent="unknown",
            tools=[],
            deep_thinking=False,
            reasoning="Failed to parse LLM response",
            orchestration_strategy=self._default_orchestration_strategy(),
        )

    def _apply_research_guardrail(
        self,
        *,
        user_message: str,
        decision: ContextDecision,
        available_tools: List[Dict[str, Any]],
    ) -> ContextDecision:
        return apply_research_guardrail(
            user_message=user_message,
            decision=decision,
            available_tools=available_tools,
            max_tools=self.max_tools,
            strategy_factory=self._default_orchestration_strategy,
        )

    def _rule_based_fallback(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
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
                        deep_thinking=False,
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
                    deep_thinking=False,
                    reasoning="The user is asking for concrete recent tool execution details, so query the persisted trace.",
                    orchestration_strategy=self._default_orchestration_strategy(),
                )

        # Complex planning/exploration: prefer worker agent tool.
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
                deep_thinking=True,
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
                deep_thinking=True,
                reasoning="Complex research request detected, routing to generic parent-task decomposition.",
                orchestration_strategy=self._default_orchestration_strategy(tools[: self.max_tools], user_lower),
            )

        # Web page fetch and extraction
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

        # Real-time queries (weather, news, stocks)
        if any(kw in user_lower for kw in ["天气", "weather", "气温", "temperature", "news", "新闻", "股票", "stock", "汇率", "exchange rate"]):
            # Prefer dedicated weather tool for weather-related requests.
            if any(kw in user_lower for kw in ["天气", "weather", "气温", "temperature"]) and "weather" in available_tools:
                tools.append("weather")
            elif "web-search" in available_tools:
                tools.append("web-search")
            else:
                tools.append("bash")
            intent = "realtime_query"

        # File operations
        if any(kw in user_lower for kw in ["读取file", "read file", "查看file", "打开file", "fileContent"]):
            tools.append("file_read")
            intent = "file_read"
        if any(kw in user_lower for kw in ["写入file", "write file", "savefile", "createfile"]):
            tools.append("file_write")
            intent = "file_write"

        # Bash operations
        if any(kw in user_lower for kw in ["Executecommand", "runcommand", "bash", "shell", "commandrow"]):
            tools.append("bash")
            intent = "command_execution"

        # Screenshot/browser
        if any(kw in user_lower for kw in ["截图", "screenshot", "网页", "website", "浏览器"]):
            if "截图" in user_lower or "screenshot" in user_lower:
                tools.append("bash")  # Use bash for screenshot
            intent = "web_interaction"

        # Skills
        for skill_name in self.tool_registry._skills.keys():
            if f"/{skill_name}" in user_message or skill_name in user_lower:
                tools.append(f"/{skill_name}")
                intent = f"skill_{skill_name}"
                break

        logger.info(f"[ContextDecider] Rule-based fallback | Intent: {intent} | Tools: {tools}")

        return ContextDecision(
            intent=intent,
            tools=tools[:self.max_tools],
            deep_thinking=False,
            reasoning="Rule-based fallback (LLM returned empty/incomplete response)",
            orchestration_strategy=self._default_orchestration_strategy(tools[:self.max_tools], user_lower),
        )

    def _apply_memory_guidance(
        self,
        *,
        user_message: str,
        context: Optional[Dict[str, Any]],
        decision: ContextDecision,
        available_tools: List[Dict[str, Any]],
    ) -> ContextDecision:
        return apply_memory_guidance(
            user_message=user_message,
            context=context,
            decision=decision,
            available_tools=available_tools,
            max_tools=self.max_tools,
        )


    def _default_orchestration_strategy(
        self,
        tools: Optional[List[str]] = None,
        user_lower: str = "",
    ) -> Dict[str, Any]:
        return default_orchestration_strategy(tools, user_lower)

    def _is_complex_research_request(self, user_lower: str) -> bool:
        return is_complex_research_request(user_lower)

    def _needs_fetch_for_request(self, user_lower: str) -> bool:
        return needs_fetch_for_request(user_lower)

    def _normalize_orchestration_strategy(self, payload: Any) -> Dict[str, Any]:
        return normalize_orchestration_strategy(payload)

    def evaluate_memory_need(
        self,
        user_message: str,
        context: dict
    ) -> Optional[MemoryGuidance]:
        """Evaluate whether memory retrieval would help answer the user's query.

        Returns a boolean recommendation only. The core chat LLM is the
        single decision point for the ``memory_query`` tool's parameters
        (``query_mode``, ``time_range``, ``sources``, ``summary_categories``)
        — the schema description tells it how. No pre-call parameter
        injection is performed here, so the chat LLM is not biased by
        rule-based guesses that historically misrouted queries like
        "我最近在用 chrome 看什么".

        Args:
            user_message: User's message.
            context: Current context (unused; kept for signature stability).

        Returns:
            MemoryGuidance(recommended=True, route="explicit_query") when
            the message looks like a recall / preference / activity-recap
            request; otherwise ``None``.
        """
        return evaluate_memory_need(user_message, context)

