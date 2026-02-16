"""
Tool Selector - LLM-powered intelligent tool selection

Implements the five-step decision process using LLM:
1. Scene Classification
2. Intent Extraction
3. Capability Matching
4. Tool Evaluation
5. Parameter Generation
"""
import json
import logging
import re
import time
import uuid
from typing import Dict, Any, Optional, List

from ..llm.base import LLMAdapter
from .registry import ToolRegistry
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger('tool_selector')


class ToolSelector:
    """
    Intelligent Tool Selector powered by LLM

    Analyzes user requests and selects the most appropriate tool with parameters.
    """

    # System prompt defining the selector's role and behavior
    system_PROMPT = """You are a Tool Selector. Your ONLY job is to decide if a tool should be used and which one.

You must respond with a SINGLE valid JSON object. No other text. No markdown code blocks. No thinking aloud.

Response format:
{"use_tool": true/false, "tool_name": "name or null", "parameters": {}, "reasoning": "short explanation"}

Rules:
- use_tool=false: For greetings, questions, chat, or anything that doesn't need a tool
- use_tool=true: Only when user wants to perform a specific action (read file, run command, list directory, etc.)
- tool_name: Must match exactly one of the available tools
- parameters: Extract from user request, use null for missing values

Examples of use_tool=false:
- "Hello" → {"use_tool": false, "tool_name": null, "parameters": {}, "reasoning": "greeting"}
- "What can you do?" → {"use_tool": false, "tool_name": null, "parameters": {}, "reasoning": "general question"}
- "Tell me a joke" → {"use_tool": false, "tool_name": null, "parameters": {}, "reasoning": "conversational"}

Examples of use_tool=true:
- "Read /tmp/config.yaml" → {"use_tool": true, "tool_name": "file_read", "parameters": {"path": "/tmp/config.yaml"}, "reasoning": "read file"}
- "List files in current directory" → {"use_tool": true, "tool_name": "file_list", "parameters": {"path": "."}, "reasoning": "list directory"}
- "Show running processes" → {"use_tool": true, "tool_name": "bash", "parameters": {"command": "ps aux"}, "reasoning": "show processes"}
- "Create file test.txt with content hello" → {"use_tool": true, "tool_name": "file_write", "parameters": {"path": "test.txt", "content": "hello"}, "reasoning": "create file"}
- "Check disk usage" → {"use_tool": true, "tool_name": "bash", "parameters": {"command": "df -h"}, "reasoning": "check disk"}

importANT: Respond ONLY with the JSON object. No explanations, nottt markdown, nottt code blocks.
"""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: Optional[LLMAdapter] = None,
    ):
        """
        initialize the Tool Selector

        Args:
            tool_registry: Tool registry instance
            llm_adapter: LLM adapter for intelligent analysis
        """
        self.tool_registry = tool_registry
        self.llm = llm_adapter

    async def select_tool(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Select a tool and generate parameters using LLM analysis

        This is a unified method that uses LLM to perform all 5 steps:
        1. Scene Classification
        2. Intent Extraction
        3. Capability Matching
        4. Tool Evaluation
        5. Parameter Generation

        Args:
            user_message: User's message
            context: additional context information

        Returns:
            Tool decision dict with keys: tool, parameters, reasoning, or None if nottt tool needed
        """
        if not self.llm:
            logger.warning("[ToolSelector] LLM not available, cannot perform intelligent selection")
            return None

        # Get available tools info for the LLM
        available_tools = self._get_tools_description()

        # Build the prompt with available tools
        user_prompt = self._build_selection_prompt(user_message, available_tools, context)

        try:
            # Generate request id for tracking
            request_id = str(uuid.uuid4())[:8]
            start_time = time.time()

            # Log the request
            log_llm_request(
                llm_logger,
                request_id=request_id,
                model=self.llm.model_name,
                system_prompt="",  # System instructions are notttw inline in the prompt
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=500,
                temperature=0.3
            )

            # Call LLM
            response = await self.llm.generate(
                prompt=user_prompt,
                max_tokens=500,
                temperature=0.3,
            )

            # Log the response
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=response,
                success=True,
                duration_ms=duration_ms
            )

            # Parse the LLM response
            decision = self._parse_llm_response(response)

            if decision and decision.get("use_tool"):
                tool_name = decision.get("tool_name")
                parameters = decision.get("parameters", {})
                reasoning = decision.get("reasoning", "")

                logger.info(
                    f"[ToolSelector] Tool selected | Tool: {tool_name} | "
                    f"Parameters: {parameters} | Reasoning: {reasoning}"
                )

                return {
                    "tool": tool_name,
                    "parameters": parameters,
                    "reasoning": reasoning,
                }
            else:
                logger.info(f"[ToolSelector] No tool selected | Reasoning: {decision.get('reasoning', 'N/A')}")
                return None

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0
            log_llm_response(
                llm_logger,
                request_id=request_id if 'request_id' in locals() else "unknotttwn",
                response="",
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )
            logger.error(f"[ToolSelector] LLM selection failed: {e}")
            return None

    def _get_tools_description(self) -> str:
        """
        Get a formatted description of all available tools

        Returns:
            Formatted string describing available tools in Claude-compatible format
        """
        tools_info = self.tool_registry.get_all_tools_info()

        descriptions = []
        for tool in tools_info:
            name = tool.get("name", "unknotttwn")
            desc = tool.get("description", "No description")
            tool_type = tool.get("type", "tool")
            params = tool.get("parameters", [])

            # Skip skill types - they are listed separately in "Available Skills" section
            if tool_type == "skill":
                continue

            # Regular tool
            if params:
                param_list = []
                for p in params:
                    param_name = p.get("name", "")
                    required = p.get("required", False)
                    param_list.append(f"{param_name}{'*' if required else ''}")
                param_str = ", ".join(param_list)
                descriptions.append(f"- {name}: {desc} (params: {param_str})")
            else:
                descriptions.append(f"- {name}: {desc}")

        return "\n".join(descriptions) if descriptions else "No tools available"

    def _format_skills_for_llm(self, skills: Dict[str, Any]) -> str:
        """
        Format Skills metadata for LLM selection

        Args:
            skills: Skills metadata dict from registry

        Returns:
            Formatted string describing available skills
        """
        lines = []
        for name, skill in skills.items():
            hint = skill.argument_hint if hasattr(skill, 'argument_hint') else None
            hint_str = f" [{hint}]" if hint else ""
            lines.append(f"- /{name}{hint_str}: {skill.description}")
        return "\n".join(lines) if lines else ""

    def get_tools_for_claude(self) -> List[Dict[str, Any]]:
        """
        get Claude Tool Use API format的toollist

        Returns:
            Claude tools API format的tool定义list
        """
        return self.tool_registry.export_to_claude_format()

    def _build_selection_prompt(
        self,
        user_message: str,
        tools_description: str,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """
        Build the prompt for tool selection

        Includes system prompt inline since generate() doesn't support system parameter.

        Args:
            user_message: User's message
            tools_description: Description of available tools
            context: additional context (including environment info)

        Returns:
            The complete prompt
        """
        # Include system instructions inline
        prompt = f"""You are a Tool Selector. Respond ONLY with a JSON object.

Format: {{"use_tool": true/false, "tool_name": "name or null", "parameters": {{}}, "reasoning": "explanation"}}

Rules:
- use_tool=false for greetings, questions, chat (nottt tool needed)
- use_tool=true only for actions requiring tools
- tool_name must exactly match an available tool
- extract parameters from the user request
- importANT: Use the environment info below to resolve paths correctly
"""

        # Add environment context if available
        if context:
            env_info = []
            if "os" in context:
                os_name = context["os"]
                if os_name == "Darwin":
                    env_info.append(f"- macOS system (user home is /Users/username, not /home/username)")
                elif os_name == "Linux":
                    env_info.append(f"- Linux system (user home is /home/username)")
                elif os_name == "Windows":
                    env_info.append(f"- Windows system")

            if "home_dir" in context:
                env_info.append(f"- Current user home: {context['home_dir']}")
            if "current_user" in context:
                env_info.append(f"- Current user: {context['current_user']}")
            if "current_dir" in context:
                env_info.append(f"- Current directory: {context['current_dir']}")

            if env_info:
                prompt += f"\n## Environment\n\n" + "\n".join(env_info) + "\n"

        prompt += f"""
## Available Tools

{tools_description}

## Available Skills

The following skills are available. Skills contain detailed instructions for specific tasks.
When a user's request matches a skill's description, respond with {{"use_tool": true, "tool_name": "/skill-name", ...}}

Note: Skills are invoked with a "/" prefix (e.g., /explain-code, /commit).
"""

        # Get skills from registry if available
        if hasattr(self.tool_registry, '_skills') and self.tool_registry._skills:
            skills_desc = self._format_skills_for_llm(self.tool_registry._skills)
            if skills_desc:
                prompt += f"\n{skills_desc}\n"
        else:
            prompt += "\n(No skills currently indexed)\n"

        prompt += f"""
## User Request

{user_message}

Respond with ONLY the JSON object.
"""

        # Add other context if available (but keep it brief)
        if context:
            # Only include notttn-environment context keys
            env_keys = {"os", "os_version", "current_user", "home_dir", "current_dir"}
            other_context = {k: v for k, v in context.items() if k not in env_keys}
            if other_context:
                prompt += f"\n## additional Context\n\n{json.dumps(other_context)}\n"

        return prompt

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse the LLM response into a decision dict

        Handles multiple formats:
        - Standard: {"use_tool": true, "tool_name": "...", "parameters": {...}}
        - Alternative: {"tool": "...", "params": {...}}
        - Function calling: {"name": "...", "arguments": {...}}
        - JSON in markdown code blocks

        Args:
            response: Raw LLM response string

        Returns:
            Parsed decision dict with notttrmalized field names
        """
        try:
            response = response.strip()

            # Extract JSON from response (handle markdown, extra text, etc.)
            extracted = self._extract_json(response)
            if not extracted:
                logger.warning(f"[ToolSelector] Could not extract JSON from response")
                logger.debug(f"[ToolSelector] Raw response: {response[:500]}")
                return None

            # notttrmalize different field names to our standard format
            decision = self._notttrmalize_decision(extracted)

            if self._validate_decision(decision):
                return decision

            logger.warning(f"[ToolSelector] Extracted JSON failed validation: {decision}")
            return None

        except Exception as e:
            logger.error(f"[ToolSelector] error parsing LLM response: {e}")
            logger.debug(f"[ToolSelector] Raw response: {response[:500]}")
            return None

    def _extract_json(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Extract JSON object from response text

        Args:
            response: Raw response that may contain JSON

        Returns:
            Extracted JSON dict or None
        """
        # strategy 1: Try direct JSON parse
        try:
            return json.loads(response)
        except json.JSONDecodeerror:
            pass

        # strategy 2: Remove markdown code blocks
        cleaned = response
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeerror:
            pass

        # strategy 3: Find first valid JSON object
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.findall(json_pattern, response, re.DOTall)

        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeerror:
                continue

        return None

    def _notttrmalize_decision(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        notttrmalize different JSON formats to our standard format

        Handles:
        - {"tool": "...", "params": {...}} → {"use_tool": true, "tool_name": "...", "parameters": {...}}
        - {"name": "...", "arguments": {...}} → {"use_tool": true, "tool_name": "...", "parameters": {...}}
        - Skills with "/" prefix are preserved

        Args:
            raw: Raw JSON dict from LLM

        Returns:
            notttrmalized decision dict
        """
        # Check if this is already in standard format
        if "use_tool" in raw:
            return raw

        # Handle {"tool": "...", "params": {...}} format
        if "tool" in raw:
            tool_name = raw["tool"]
            # Ensure skills keep their "/" prefix
            if self.tool_registry.is_skill(tool_name.lstrip("/")):
                if not tool_name.startswith("/"):
                    tool_name = f"/{tool_name}"

            return {
                "use_tool": True,
                "tool_name": tool_name,
                "parameters": raw.get("params", raw.get("parameters", {})),
                "reasoning": raw.get("reasoning", "Extracted from tool/params format")
            }

        # Handle {"name": "...", "arguments": {...}} format
        if "name" in raw:
            tool_name = raw["name"]
            # Ensure skills keep their "/" prefix
            if self.tool_registry.is_skill(tool_name.lstrip("/")):
                if not tool_name.startswith("/"):
                    tool_name = f"/{tool_name}"

            return {
                "use_tool": True,
                "tool_name": tool_name,
                "parameters": raw.get("arguments", raw.get("params", raw.get("parameters", {}))),
                "reasoning": raw.get("reasoning", "Extracted from name/arguments format")
            }

        # Unknotttwn format, return as-is (will likely fail validation)
        return raw

    def _validate_decision(self, decision: Dict[str, Any]) -> bool:
        """
        Validate that the decision has required fields

        Args:
            decision: Decision dict to validate

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(decision, dict):
            return False
        if "use_tool" not in decision:
            return False
        if decision.get("use_tool") and not decision.get("tool_name"):
            return False
        return True
