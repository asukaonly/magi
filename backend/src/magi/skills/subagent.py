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
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from .schema import SkillContent, SkillResult
from magi_plugin_sdk.turn import UserTurnInput
from ..chat.workspace import get_default_chat_workspace_path
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..config.constants import DEFAULT_SKILL_MAX_TOKENS

if TYPE_CHECKING:
    from ..agent.execution.function_calling import FunctionCallingOrchestrator
    from ..tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# Maximum number of nested fork-mode skill invocations allowed in a single
# task. Direct-mode skills are unaffected — they share the parent context
# and don't recurse the same way. Configurable via env var because the
# right ceiling depends on how composable a workspace's skill library is.
import contextvars as _contextvars
import os as _os


def _resolve_max_fork_depth() -> int:
    raw = _os.environ.get("MAGI_SKILLS_MAX_FORK_DEPTH", "").strip()
    if not raw:
        return 3
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(1, value)


MAX_FORK_DEPTH = _resolve_max_fork_depth()
_fork_depth: _contextvars.ContextVar[int] = _contextvars.ContextVar(
    "magi_skill_fork_depth", default=0
)


class SkillForkDepthExceeded(RuntimeError):
    """Raised when a fork-mode skill recurses past ``MAX_FORK_DEPTH``."""


def _get_tool_registry():
    """Lazy import to avoid circular dependency."""
    from ..tools.registry import tool_registry
    return tool_registry


def _get_function_calling_orchestrator(
    llm_adapter,
    tool_registry,
    skill_runner,
    tool_result_callback,
    permission_gateway_provider: Callable[[], Any] | None = None,
):
    """Lazy import to avoid circular dependency."""
    from ..agent.execution.function_calling import FunctionCallingOrchestrator
    return FunctionCallingOrchestrator(
        llm_adapter=llm_adapter,
        tool_registry=tool_registry,
        skill_runner=skill_runner,
        tool_result_callback=tool_result_callback,
        permission_gateway_provider=permission_gateway_provider,
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
        permission_gateway_provider: Callable[[], Any] | None = None,
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
        self.permission_gateway_provider = permission_gateway_provider
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
        Return the full tool list available to this subagent.

        Per the Claude Code Skills spec, ``allowed-tools`` is a
        *pre-approval* list, not a restriction on which tools can be
        called. The subagent therefore sees every registered tool; the
        skill's allowed-tools rules are used only to skip permission
        prompts for matching calls (see
        :mod:`magi.skills.active_restrictions`).

        ``self.allowed_tools`` is retained for telemetry / logging only.
        """
        return _get_tool_registry().list_tools()

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

        # Fork-depth guard: a contextvar tracks how many nested fork-mode
        # skills are currently on the call stack of this asyncio task.
        # Going past MAX_FORK_DEPTH would let a skill that fork-invokes
        # itself (directly or transitively) blow up token usage and
        # latency without bound, so we cut it off here.
        depth = _fork_depth.get()
        if depth >= MAX_FORK_DEPTH:
            logger.warning(
                "SkillSubagent fork depth exceeded | skill=%s depth=%d max=%d",
                self.skill.name,
                depth,
                MAX_FORK_DEPTH,
            )
            return SkillResult(
                success=False,
                error=(
                    f"Fork-mode skill '{self.skill.name}' rejected: nesting "
                    f"depth would exceed MAX_FORK_DEPTH={MAX_FORK_DEPTH}. "
                    f"Set MAGI_SKILLS_MAX_FORK_DEPTH to override."
                ),
                execution_time=0.0,
            )
        depth_token = _fork_depth.set(depth + 1)

        logger.info(
            f"SkillSubagent executing | id={self.subagent_id} | depth={depth + 1}"
        )

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
        finally:
            _fork_depth.reset(depth_token)

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
                permission_gateway_provider=self.permission_gateway_provider,
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
            turn=UserTurnInput(
                text=user_message,
                attachments=[],
                user_id=context.get("user_id", "subagent"),
                session_id=self.subagent_id,
            ),
            system_prompt=full_system_prompt,
            selected_tools=self._available_tools,
            user_id=context.get("user_id", "subagent"),
            session_id=self.subagent_id,
            conversation_history=[],
            disable_thinking=True,
            intent="skill_execution",
            execution_workspace=self._resolve_workspace(context),
        )

        if not result.succeeded:
            raise RuntimeError(result.failure_reason or "Skill subagent execution failed")
        return result.content

    def _resolve_workspace(self, context: Dict[str, Any]) -> str:
        env_vars = context.get("env_vars", {})
        raw_workspace = (
            str(context.get("workspace", "")).strip()
            or str(env_vars.get("PWD", "")).strip()
            or get_default_chat_workspace_path()
        )
        return str(Path(raw_workspace).expanduser().resolve())

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
    permission_gateway_provider: Callable[[], Any] | None = None,
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
        permission_gateway_provider=permission_gateway_provider,
    )
