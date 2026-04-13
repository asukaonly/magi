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
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, List as TypingList

from ..agent.message_utils import trim_latest_user_message
from ..config.models import LLMScenario, ThinkingDepth
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..config.constants import DEFAULT_MAX_TOKENS, DEFAULT_THINKING_TOKENS
from .registry import ToolRegistry
from .context_decider_context import ContextDeciderContext
from .memory_query_hint_resolver import MemoryQueryHintResolver
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger('context_decider')


class ContextDecision:
    """Context decision result"""

    def __init__(
        self,
        intent: str,
        tools: List[str],
        deep_thinking: bool = False,
        reasoning: str = "",
        orchestration_strategy: Optional[Dict[str, Any]] = None,
        memory_layer: Optional[str] = None,  # TODO: implement memory layer selection
        memory_route: str = "none",
        routing_memory_hint: Optional[Dict[str, Any]] = None,
        llm_trace: Optional[Dict[str, Any]] = None,
        thinking_depth: Optional[ThinkingDepth] = None,
    ):
        self.intent = intent  # User's intent (e.g., "file_read", "web_search", "chat")
        self.tools = tools  # List of up to 5 tool names
        self.reasoning = reasoning  # Why these tools were selected
        self.orchestration_strategy = orchestration_strategy or {}
        self.memory_layer = memory_layer  # Which memory layer to use (L1-L4)
        self.memory_route = memory_route
        self.routing_memory_hint = routing_memory_hint
        self.llm_trace = dict(llm_trace or {})

        # Thinking depth: use explicit value if provided, otherwise derive from legacy bool
        if thinking_depth is not None:
            self.thinking_depth = thinking_depth
        elif deep_thinking:
            self.thinking_depth = ThinkingDepth.HIGH
        else:
            self.thinking_depth = ThinkingDepth.NONE

    @property
    def deep_thinking(self) -> bool:
        """Legacy accessor: True when thinking_depth is MEDIUM or above."""
        return self.thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW)


@dataclass
class ToolRecommendation:
    """Tool recommendation with suggested parameters."""
    name: str
    description: str
    suggested_params: dict


@dataclass
class MemoryGuidance:
    """Memory retrieval guidance from ContextDecider."""
    recommended: bool
    inject_prompt: bool
    system_prompt: str
    recommended_tools: TypingList[ToolRecommendation]
    route: str = "none"


# Memory retrieval trigger keywords
MEMORY_RETRIEVAL_TRIGGERS = [
    "what did i", "what was i", "what have i",
    "yesterday", "last week", "last month", "recently",
    "browsing", "browse", "visited", "watched", "read",
    "my history", "my activity", "my notes", "my chat",
    "browse yesterday", "最近", "浏览", "看", "读",
]


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

**Prefer `web-search` when:**
- Identifying unknown processes, executables, or software (e.g., "what is xxx.exe")
- The user asks about something they don't recognize on their system
- Local commands alone cannot determine the identity or safety of an unknown program
- Combine with `bash` when local verification (e.g., checking file signatures) is also useful

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

User: "帮我看看我的电脑，我看进程里有Aac3572MbHal_x86.exe这么个，这是干嘛的"
JSON: {"intent": "realtime_query", "tools": ["web-search", "bash"], "thinking_depth": "low", "reasoning": "Identifying an unknown process/executable. Use web-search first to determine what it is, then optionally bash to verify locally (file signature, publisher, location).", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

User: "what is svchost.exe and why is it using so much memory"
JSON: {"intent": "realtime_query", "tools": ["web-search", "bash"], "thinking_depth": "low", "reasoning": "User wants to identify a process and understand its resource usage. Web search for identification, bash for local resource inspection.", "orchestration_strategy": {"mode": "direct", "planner": "task_agent", "default_leaf_type": "general-purpose", "allow_parallel": false}}

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
        self._memory_query_hint_resolver = MemoryQueryHintResolver()

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
        prompt = """## Available Tools

"""

        for tool in available_tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "No description")
            prompt += f"- {name}: {desc}\n"

        # Add skills with truncated descriptions and trigger keywords
        if hasattr(self.tool_registry, '_skills') and self.tool_registry._skills:
            prompt += "\n## Available Skills\n\n"
            for name, skill in self.tool_registry._skills.items():
                desc = skill.description if hasattr(skill, 'description') else "No description"
                # Truncate long descriptions (keep first 150 chars)
                if len(desc) > 150:
                    desc = desc[:150] + "..."
                prompt += f"- /{name}: {desc}\n"

        prompt += f"""
## User Request

{user_message}

## Environment

"""
        if context:
            if context.os_name:
                os_line = context.os_name
                if context.os_version:
                    os_line = f"{os_line} {context.os_version}"
                prompt += f"- OS: {os_line}\n"
            if context.current_datetime:
                prompt += f"- Current datetime: {context.current_datetime}\n"
            if context.timezone:
                prompt += f"- Timezone: {context.timezone}\n"
            if context.workspace_path:
                prompt += f"- Workspace path: {context.workspace_path}\n"
            if context.home_dir:
                prompt += f"- Home directory: {context.home_dir}\n"
            recent_messages = context.recent_messages
            if isinstance(recent_messages, list) and recent_messages:
                recent_messages = trim_latest_user_message(recent_messages, user_message)
            if isinstance(recent_messages, list) and recent_messages:
                prompt += "\n## Recent Conversation\n\n"
                for item in recent_messages[-6:]:
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("role", "unknown"))
                    content = str(item.get("content", ""))
                    prompt += f"- {role}: {content}\n"
            recent_tool_errors = context.recent_tool_errors
            if isinstance(recent_tool_errors, list) and recent_tool_errors:
                prompt += "\n## Recent Tool Errors\n\n"
                for item in recent_tool_errors[:3]:
                    if not isinstance(item, dict):
                        continue
                    tool_name = str(item.get("tool_name", "unknown"))
                    error_code = str(item.get("error_code", "UNKNOWN"))
                    error_message = str(item.get("error_message", ""))
                    config_path = str(item.get("config_path") or "").strip()
                    next_action = str(item.get("next_action") or "").strip()
                    line = f"- {tool_name}: {error_code} | {error_message}"
                    if config_path:
                        line += f" | config_path={config_path}"
                    if next_action:
                        line += f" | next_action={next_action}"
                    prompt += f"{line}\n"
        else:
            prompt += "- No environment info\n"

        prompt += "\nRespond with ONLY the JSON object."

        return prompt

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
        user_lower = user_message.lower()
        if not self._is_complex_research_request(user_lower):
            return decision
        available_names = {str(item.get("name", "")).strip() for item in available_tools}
        tools: list[str] = []
        if "web-search" in available_names:
            tools.append("web-search")
        if self._needs_fetch_for_request(user_lower) and "web-fetch" in available_names:
            tools.append("web-fetch")
        if not tools and "bash" in available_names:
            tools.append("bash")
        return ContextDecision(
            intent="planning",
            tools=tools[: self.max_tools],
            deep_thinking=True,
            reasoning="Complex research request guardrail: force bounded generic decomposition with explicit retrieval steps.",
            orchestration_strategy=self._default_orchestration_strategy(tools[: self.max_tools], user_lower),
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
        guidance = self.evaluate_memory_need(user_message, context or {})
        if guidance is None or not guidance.recommended:
            return decision
        available_names = {str(item.get("name", "")).strip() for item in available_tools}
        if "memory_query" not in available_names:
            return decision
        tools = list(decision.tools)
        if "memory_query" not in tools:
            tools.append("memory_query")
        return ContextDecision(
            intent=decision.intent,
            tools=tools[: self.max_tools],
            deep_thinking=decision.deep_thinking,
            reasoning=decision.reasoning,
            orchestration_strategy=decision.orchestration_strategy,
            memory_layer=decision.memory_layer,
            memory_route=guidance.route,
            routing_memory_hint=(
                guidance.recommended_tools[0].suggested_params
                if guidance.recommended_tools
                else None
            ),
        )

    def _default_orchestration_strategy(
        self,
        tools: Optional[List[str]] = None,
        user_lower: str = "",
    ) -> Dict[str, Any]:
        selected_tools = tools or []
        if self._is_complex_research_request(user_lower):
            return {
                "mode": "decompose",
                "planner": "task_agent",
                "default_leaf_type": "general-purpose",
                "allow_parallel": True,
            }
        if "agent" in selected_tools:
            if any(kw in user_lower for kw in ["migration", "migrate", "实施方案", "design doc", "implementation plan"]):
                return {
                    "mode": "decompose",
                    "planner": "plan_worker",
                    "default_leaf_type": "Explore",
                    "allow_parallel": True,
                }
            if any(
                kw in user_lower
                for kw in ["架构", "architecture", "设计", "方案", "codebase", "repo", "代码结构", "代码库", "跨模块", "跨子系统"]
            ):
                return {
                    "mode": "decompose",
                    "planner": "task_agent",
                    "default_leaf_type": "Explore",
                    "allow_parallel": True,
                }
            if any(kw in user_lower for kw in ["explore", "scan", "搜索", "定位", "查找", "find"]):
                return {
                    "mode": "direct",
                    "planner": "task_agent",
                    "default_leaf_type": "Explore",
                    "allow_parallel": False,
                }
        return {
            "mode": "direct",
            "planner": "task_agent",
            "default_leaf_type": "general-purpose",
            "allow_parallel": False,
        }

    def _is_complex_research_request(self, user_lower: str) -> bool:
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

    def _needs_fetch_for_request(self, user_lower: str) -> bool:
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

    def _normalize_orchestration_strategy(self, payload: Any) -> Dict[str, Any]:
        strategy = self._default_orchestration_strategy()
        if not isinstance(payload, dict):
            return strategy
        mode = str(payload.get("mode", strategy["mode"])).strip()
        planner = str(payload.get("planner", strategy["planner"])).strip()
        default_leaf_type = str(payload.get("default_leaf_type", strategy["default_leaf_type"])).strip()
        allow_parallel = bool(payload.get("allow_parallel", strategy["allow_parallel"]))
        if mode not in {"direct", "decompose"}:
            mode = strategy["mode"]
        if planner not in {"task_agent", "plan_worker"}:
            planner = strategy["planner"]
        if default_leaf_type not in {"Explore", "general-purpose"}:
            default_leaf_type = strategy["default_leaf_type"]
        if mode == "direct":
            allow_parallel = False
        return {
            "mode": mode,
            "planner": planner,
            "default_leaf_type": default_leaf_type,
            "allow_parallel": allow_parallel,
        }

    def evaluate_memory_need(
        self,
        user_message: str,
        context: dict
    ) -> Optional[MemoryGuidance]:
        """
        Evaluate if memory retrieval would help answer the user's query.

        Only determines whether memory_query should be triggered.
        Time/type inference is handled by the IntentDecider inside
        HybridRetrievalService.

        Args:
            user_message: User's message
            context: Current context (date, etc.)

        Returns:
            MemoryGuidance if memory retrieval is recommended, None otherwise.
        """
        message_lower = user_message.lower()
        if not self._memory_query_hint_resolver.should_route_explicitly(user_message):
            return None
        suggested_params = self._memory_query_hint_resolver.resolve(user_message)

        return MemoryGuidance(
            recommended=True,
            inject_prompt=False,
            system_prompt=(
                "Based on the user's query, memory retrieval may be helpful. "
                "Consider using the memory_query tool to access relevant historical data."
            ),
            recommended_tools=[
                ToolRecommendation(
                    name="memory_query",
                    description="Retrieve memories from L0-L4 layers",
                    suggested_params=suggested_params,
                )
            ],
            route="explicit_query",
        )

    def _infer_time_range(self, message_lower: str) -> dict:
        """Infer time range from message content.

        .. deprecated::
            Time range inference has moved to IntentDecider.
            Kept for backward compatibility; will be removed.
        """
        if "yesterday" in message_lower or "昨天" in message_lower:
            return {"relative": "1d"}
        elif "last week" in message_lower or "上周" in message_lower:
            return {"relative": "7d"}
        elif "last month" in message_lower or "上个月" in message_lower:
            return {"relative": "30d"}
        elif "recently" in message_lower or "最近" in message_lower:
            return {"relative": "7d"}
        else:
            return {"relative": "7d"}

    def _infer_memory_types(self, message_lower: str) -> Optional[list]:
        """Infer memory types from message content.

        .. deprecated::
            Memory type inference has moved to IntentDecider.
            Kept for backward compatibility; will be removed.
        """
        types = []
        if any(kw in message_lower for kw in ["browse", "visit", "website", "浏览", "网页"]):
            types.append("chrome_history")
        if any(kw in message_lower for kw in ["chat", "conversation", "对话", "聊天"]):
            types.append("chat")
        if any(kw in message_lower for kw in ["note", "笔记", "记录"]):
            types.append("note")
        return types if types else None
