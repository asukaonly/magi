"""
Skill Subagent - Isolated execution context for skills

Provides a dedicated agent instance for skill execution with:
- Restricted tool access (allowed_tools)
- Script execution capability
- Independent conversation context
"""
from __future__ import annotations

import logging
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from .schema import SkillContent, SkillResult
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..config.constants import DEFAULT_SKILL_MAX_TOKENS

if TYPE_CHECKING:
    from ..agent.execution.function_calling import FunctionCallingOrchestrator
    from ..tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _get_tool_registry():
    """Lazy import to avoid circular dependency."""
    from ..tools.registry import tool_registry
    return tool_registry


def _get_function_calling_orchestrator(llm_adapter, tool_registry, skill_runner, tool_result_callback):
    """Lazy import to avoid circular dependency."""
    from ..agent.execution.function_calling import FunctionCallingOrchestrator
    return FunctionCallingOrchestrator(
        llm_adapter=llm_adapter,
        tool_registry=tool_registry,
        skill_runner=skill_runner,
        tool_result_callback=tool_result_callback,
    )


class SkillSubagent:
    """
    Isolated execution context for skill execution.

    Unlike the main ChatTaskAgent, this is a lightweight, one-shot executor
    that provides:
    - Tool restriction via allowed_tools
    - Script execution from skill's scripts/ directory
    - Independent context from the main conversation
    """

    def __init__(
        self,
        skill: SkillContent,
        llm_adapter: LLMAdapter,
        allowed_tools: Optional[List[str]] = None,
    ):
        """
        Initialize the skill subagent.

        Args:
            skill: The skill content to execute
            llm_adapter: LLM adapter for model calls
            allowed_tools: List of allowed tool names (None = all tools allowed)
        """
        self.skill = skill
        self.llm = llm_adapter
        self.allowed_tools: Optional[Set[str]] = set(allowed_tools) if allowed_tools else None
        self.subagent_id = f"skill-{skill.name}-{uuid.uuid4().hex[:8]}"

        # Create restricted tool registry view
        self._available_tools = self._build_available_tools()

        # Create function calling orchestrator with restricted tools (lazy)
        self._function_calling_orchestrator = None

        logger.info(
            f"SkillSubagent created | id={self.subagent_id} | "
            f"skill={skill.name} | allowed_tools={allowed_tools}"
        )

    def _build_available_tools(self) -> List[str]:
        """
        Build list of available tools based on allowed_tools restriction.

        Returns:
            List of tool names available to this subagent
        """
        registry = _get_tool_registry()
        all_tools = registry.list_tools()  # Returns list of tool names

        if self.allowed_tools is None:
            return all_tools

        # Filter to only allowed tools
        available = [t for t in all_tools if t in self.allowed_tools]

        # Always include bash for script execution
        if "bash" not in available and self.allowed_tools is not None:
            # Check if skill has scripts - if so, bash should be available
            scripts = self.skill.supporting_data.get("scripts", [])
            if scripts:
                available.append("bash")
                logger.info(f"Auto-including 'bash' tool for skill with scripts: {self.skill.name}")

        return available

    async def execute(
        self,
        user_message: str,
        system_prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """
        Execute the skill with the given user message.

        Args:
            user_message: The user's request
            system_prompt: System prompt (skill's prompt template)
            context: Additional context (env_vars, etc.)

        Returns:
            SkillResult with execution outcome
        """
        start_time = time.time()
        context = context or {}

        logger.info(f"SkillSubagent executing | id={self.subagent_id}")

        try:
            # Check if we need tools
            needs_tools = len(self._available_tools) > 0 and self._should_use_tools(user_message)

            if needs_tools:
                result_content = await self._execute_with_tools(
                    user_message=user_message,
                    system_prompt=system_prompt,
                    context=context,
                )
            else:
                result_content = await self._execute_direct(
                    user_message=user_message,
                    system_prompt=system_prompt,
                    context=context,
                )

            execution_time = time.time() - start_time

            return SkillResult(
                success=True,
                content=result_content,
                metadata={
                    "subagent_id": self.subagent_id,
                    "skill_name": self.skill.name,
                    "allowed_tools": list(self.allowed_tools) if self.allowed_tools else None,
                    "available_tools": self._available_tools,
                    "execution_time": execution_time,
                    "mode": "subagent",
                },
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"SkillSubagent execution failed | id={self.subagent_id} | error={e}")
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=execution_time,
            )

    def _should_use_tools(self, user_message: str) -> bool:
        """
        Determine if tools should be used for this request.

        Simple heuristic: if allowed_tools is specified and non-empty,
        we assume tools might be needed.

        Args:
            user_message: The user's request

        Returns:
            True if tools should be used
        """
        # If tools are restricted, we likely need them
        if self.allowed_tools:
            return True

        # Simple heuristics for tool need
        tool_keywords = [
            "read", "write", "file", "search", "execute", "run",
            "bash", "command", "fetch", "get", "list", "directory",
        ]
        message_lower = user_message.lower()
        return any(kw in message_lower for kw in tool_keywords)

    async def _execute_with_tools(
        self,
        user_message: str,
        system_prompt: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Execute using function calling with restricted tools.

        Args:
            user_message: User's request
            system_prompt: System prompt
            context: Execution context

        Returns:
            Result content
        """
        # Lazy init function calling orchestrator
        if self._function_calling_orchestrator is None:
            registry = _get_tool_registry()
            self._function_calling_orchestrator = _get_function_calling_orchestrator(
                llm_adapter=self.llm,
                tool_registry=registry,
                skill_runner=None,
                tool_result_callback=None,
            )

        # Build system prompt with tool restrictions notice
        full_system_prompt = system_prompt
        if self.allowed_tools:
            tool_notice = (
                f"\n\nIMPORTANT: You are running in a restricted skill context. "
                f"You only have access to these tools: {', '.join(self._available_tools)}. "
                f"Do not attempt to use any other tools."
            )
            full_system_prompt = full_system_prompt + tool_notice

        # Execute with tools
        result = await self._function_calling_orchestrator.execute_with_tools(
            user_message=user_message,
            system_prompt=full_system_prompt,
            selected_tools=self._available_tools,
            user_id=context.get("user_id", "subagent"),
            session_id=self.subagent_id,
            conversation_history=[],
            disable_thinking=True,
            intent="skill_execution",
        )

        if not result.succeeded:
            raise RuntimeError(result.failure_reason or "Skill subagent execution failed")
        return result.content

    async def _execute_direct(
        self,
        user_message: str,
        system_prompt: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Execute directly without tools.

        Args:
            user_message: User's request
            system_prompt: System prompt
            context: Execution context

        Returns:
            Result content
        """
        provider_bridge = LLMProviderBridge(self.llm)
        messages = [{"role": "user", "content": user_message}]

        return await provider_bridge.chat(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=DEFAULT_SKILL_MAX_TOKENS,
            temperature=0.7,
            disable_thinking=True,
            event_context={
                "request_kind": "skill_subagent:direct",
                "session_id": self.subagent_id,
                "agent_id": self.subagent_id,
            },
        )

    async def execute_script(
        self,
        script_name: str,
        args: Optional[List[str]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Execute a script from the skill's scripts/ directory.

        Args:
            script_name: Name of the script file
            args: Arguments to pass to the script
            timeout: Execution timeout in seconds

        Returns:
            Dict with stdout, stderr, return_code, success
        """
        args = args or []

        # Find the script
        scripts = self.skill.supporting_data.get("scripts", [])
        script_path = None
        for script in scripts:
            if script.get("name") == script_name:
                script_path = Path(script.get("path", ""))
                break

        if not script_path or not script_path.exists():
            return {
                "success": False,
                "error": f"Script not found: {script_name}",
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }

        # Check if script is executable
        if not script_path.stat().st_mode & 0o111:
            # Try to make it executable
            try:
                script_path.chmod(script_path.stat().st_mode | 0o111)
            except Exception as e:
                logger.warning(f"Could not make script executable: {e}")

        logger.info(f"Executing script | skill={self.skill.name} | script={script_name}")

        try:
            result = subprocess.run(
                [str(script_path)] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(script_path.parent),
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Script execution timed out after {timeout}s",
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }

    def get_script_names(self) -> List[str]:
        """
        Get list of available script names.

        Returns:
            List of script filenames
        """
        scripts = self.skill.supporting_data.get("scripts", [])
        return [s.get("name") for s in scripts if s.get("name")]


def create_skill_subagent(
    skill: SkillContent,
    llm_adapter: LLMAdapter,
) -> SkillSubagent:
    """
    Factory function to create a SkillSubagent.

    Args:
        skill: The skill content
        llm_adapter: LLM adapter

    Returns:
        Configured SkillSubagent instance
    """
    allowed_tools = skill.frontmatter.allowed_tools
    return SkillSubagent(
        skill=skill,
        llm_adapter=llm_adapter,
        allowed_tools=allowed_tools,
    )
