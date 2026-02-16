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

from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from .registry import ToolRegistry
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
        memory_layer: Optional[str] = None,  # TODO: implement memory layer selection
    ):
        self.intent = intent  # User's intent (e.g., "file_read", "web_search", "chat")
        self.tools = tools  # List of up to 5 tool names
        self.deep_thinking = deep_thinking  # Whether to use extended reasoning mode
        self.reasoning = reasoning  # Why these tools were selected
        self.memory_layer = memory_layer  # Which memory layer to use (L1-L5)


class ContextDecider:
    """
    Context Decision Module

    Analyzes user request and selects the most relevant tools.
    Uses LLM to understand intent and match with available tools.
    """

    system_PROMPT = """You are a Context Decider, the intelligent router of an autonotttmous agent system.
Your SOLE function is to analyze the user's request and output a precise JSON configuration.

### 1. Response Format
Respond with a SINGLE valid JSON object. No markdown formatting, nottt explanations.

JSON structure:
{
  "intent": "string",
  "tools": ["string"],
  "deep_thinking": boolean,
  "reasoning": "string"
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
- Skills: Complex capabilities with specialized knotttwledge (start with /)

**Prioritize Skills when:**
- Task requires specialized knotttwledge or workflows
- User request matches a skill's description
- External resources or web access needed

**Use Tools when:**
- Simple file operations (read/write/list)
- Command execution
- No specialized knotttwledge needed

Always check the "Available Skills" section below for skill descriptions and match user requests accordingly.

### 4. Deep Thinking Threshold
Set "deep_thinking": true for:
- Architecture design or multi-file refactoring
- Complex bug diagnotttsis requiring reasoning chains
- Multi-step planning (more than 3 steps)
- Creative writing or roleplay scenarios
- Code review with modification suggestions

Set "deep_thinking": false for:
- Simple CRUD operations
- Single file read/write
- information queries (weather, time)
- Casual chat
- Executing explicit instructions (user provided steps)

### 5. Few-Shot Examples

User: "hey"
JSON: {"intent": "chat", "tools": [], "deep_thinking": false, "reasoning": "Casual greeting."}

User: "what's the weather in tokyo"
JSON: {"intent": "realtime_query", "tools": ["bash"], "deep_thinking": false, "reasoning": "Real-time weather query. Use bash curl or check for web-related skills."}

User: "read /src/main.py and fix the race condition"
JSON: {"intent": "code_execution", "tools": ["file_read", "file_write"], "deep_thinking": true, "reasoning": "Complex bug diagnotttsis required."}

User: "list files in current dir"
JSON: {"intent": "file_operation", "tools": ["file_list"], "deep_thinking": false, "reasoning": "Simple single-step action."}

Note: Always match tools/skills from the "Available Tools" and "Available Skills" lists. If nottt matching skill exists, use basic tools."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMAdapter,
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
        self.llm = llm_adapter
        self.provider_bridge = LLMProviderBridge(llm_adapter)
        self.max_tools = max_tools

    async def decide(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ContextDecision:
        """
        Analyze user request and decide on tools

        Args:
            user_message: User's message
            context: additional context (environment info, etc.)

        Returns:
            ContextDecision with selected tools
        """
        if not self.llm:
            logger.warning("[ContextDecider] LLM not available")
            return ContextDecision(
                intent="unknotttwn",
                tools=[],
                deep_thinking=False,
                reasoning="LLM not available",
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
                max_tokens=300,
                temperature=0.3,
            )

            response = await self.provider_bridge.chat(
                system_prompt=self.system_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=1000,
                temperature=0.3,
                disable_thinking=True,
            )

            # Check if response is empty or incomplete
            if not response or not response.strip():
                logger.warning("[ContextDecider] LLM returned empty response, using rule-based fallback")
                return self._rule_based_fallback(user_message)

            # Check for incomplete JSON response (just "{" or similar)
            stripped = response.strip()
            if stripped in ("{", "}", "{}"):
                logger.warning(f"[ContextDecider] LLM returned incomplete response: {stripped}, using rule-based fallback")
                return self._rule_based_fallback(user_message)

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

            logger.info(
                f"[ContextDecider] Decision made | Intent: {decision.intent} | "
                f"Tools: {decision.tools} | Deep Thinking: {decision.deep_thinking} | Reasoning: {decision.reasoning}"
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
            )

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
        context: Optional[Dict[str, Any]],
    ) -> str:
        """Build the prompt for context decision"""
        prompt = """## Available Tools

"""

        for tool in available_tools:
            name = tool.get("name", "unknotttwn")
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
            if "os" in context:
                prompt += f"- OS: {context['os']}\n"
            if "current_dir" in context:
                prompt += f"- Current directory: {context['current_dir']}\n"
            if "home_dir" in context:
                prompt += f"- Home directory: {context['home_dir']}\n"
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
                intent="unknotttwn",
                tools=[],
                deep_thinking=False,
                reasoning="Empty LLM response",
            )

        # Handle incomplete response (just `{` or similar)
        if response == "{" or response == "{}":
            logger.warning(f"[ContextDecider] Incomplete LLM response: {response}")
            return ContextDecision(
                intent="unknotttwn",
                tools=[],
                deep_thinking=False,
                reasoning="Incomplete LLM response",
            )

        # Try to extract JSON - multiple patterns
        # pattern 1: Standard nested JSON
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTall)

        # pattern 2: If pattern 1 fails, try to find any JSON-like structure
        if not json_match:
            # Try to find JSON that starts with { and ends with }
            json_match = re.search(r'\{.*\}', response, re.DOTall)

        if json_match:
            try:
                json_str = json_match.group()
                data = json.loads(json_str)

                # Validate required fields
                if not isinstance(data, dict):
                    raise ValueError("Response is not a JSON object")

                intent = data.get("intent", "unknotttwn")
                tools = data.get("tools", [])
                deep_thinking = data.get("deep_thinking", False)
                reasoning = data.get("reasoning", "")

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
                    deep_thinking=deep_thinking,
                    reasoning=reasoning,
                )
            except json.JSONDecodeerror as e:
                logger.warning(f"[ContextDecider] JSON decode error: {e}")
            except ValueError as e:
                logger.warning(f"[ContextDecider] Invalid response structure: {e}")

        # Fallback: nottt tools selected
        logger.warning(f"[ContextDecider] Failed to parse response: {response[:200]}")
        return ContextDecision(
            intent="unknotttwn",
            tools=[],
            deep_thinking=False,
            reasoning="Failed to parse LLM response",
        )

    def _rule_based_fallback(self, user_message: str) -> ContextDecision:
        """
        Rule-based tool selection as fallback when LLM fails

        Simple keyword matching to determine which tools might be needed
        """
        user_lower = user_message.lower()
        tools = []
        intent = "chat"

        # Real-time queries (weather, news, stocks)
        if any(kw in user_lower for kw in ["days气", "weather", "气温", "temperature", "news", "new闻", "股票", "stock", "汇率", "exchange rate"]):
            # Check if web-search is available
            available_tools = self.tool_registry.list_tools()
            if "web-search" in available_tools:
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
        if any(kw in user_lower for kw in ["column出directory", "list file", "查看directory", "ls", "file夹"]):
            tools.append("file_list")
            intent = "file_list"

        # Bash operations
        if any(kw in user_lower for kw in ["Executecommand", "runcommand", "bash", "shell", "commandrow"]):
            tools.append("bash")
            intent = "command_execution"

        # Screenshot/browser
        if any(kw in user_lower for kw in ["截graph", "screenshot", "网页", "website", "浏览器"]):
            if "截graph" in user_lower or "screenshot" in user_lower:
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
        )
