"""
Skill Subagent - Isolated execution context for skills

Provides a dedicated agent instance for skill execution with:
- Restricted tool access (allowed_tools)
- Script execution capability
- Independent conversation context
"""

from __future__ import annotations

import contextvars as _contextvars
import logging
import os as _os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from magi_plugin_sdk.subprocess import hidden_process_kwargs
from .schema import SkillContent, SkillResult
from .tool_registry_port import ToolRegistryPort
from magi_plugin_sdk.turn import UserTurnInput
from ..utils.runtime import get_default_chat_workspace_path
from ..llm.base import LLMAdapter

logger = logging.getLogger(__name__)


# Maximum number of nested fork-mode skill invocations allowed in a single
# task. Direct-mode skills are unaffected — they share the parent context
# and don't recurse the same way. Configurable via env var because the
# right ceiling depends on how composable a workspace's skill library is.
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
        tool_registry: ToolRegistryPort | None = None,
        orchestrator_factory: Callable[..., Any] | None = None,
        agent_run_request_factory: Callable[..., Any] | None = None,
        active_model_provider: Callable[..., Any] | None = None,
        scenario_llm_pool: Any | None = None,
    ):
        """
        Initialize the skill subagent.

        Args:
            skill: The skill content to execute
            llm_adapter: LLM adapter for model calls
            allowed_tools: List of allowed tool names (None = all tools allowed)
            tool_registry: The shared tool registry (injected by the
                composition root). When ``None`` the subagent exposes no
                tools — equivalent to an empty registry.
            orchestrator_factory: Builds the unified agent orchestrator.
                Injected by the composition root so the skills layer does not
                import the agent execution engine.
            agent_run_request_factory: Builds the headless engine run input
                (wraps ``AgentRunRequest.headless``). Injected for the same
                reason.
        """
        self.skill = skill
        self.llm = llm_adapter
        self.allowed_tools: Optional[Set[str]] = set(allowed_tools) if allowed_tools else None
        self.permission_gateway_provider = permission_gateway_provider
        self._tool_registry = tool_registry
        self._orchestrator_factory = orchestrator_factory
        self._agent_run_request_factory = agent_run_request_factory
        self._active_model_provider = active_model_provider
        self._scenario_llm_pool = scenario_llm_pool
        self.subagent_id = f"skill-{skill.name}-{uuid.uuid4().hex[:8]}"

        # Create restricted tool registry view
        self._available_tools = self._build_available_tools()

        self._agent_orchestrator = None

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
        if self._tool_registry is None:
            return []
        return self._tool_registry.list_tools()

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
            return self._fork_depth_exceeded_result(depth)
        depth_token = _fork_depth.set(depth + 1)

        logger.info(f"SkillSubagent executing | id={self.subagent_id} | depth={depth + 1}")

        try:
            result_content = await self._execute_agent_run(
                user_message=user_message,
                system_prompt=system_prompt,
                context=context,
            )
            execution_time = time.time() - start_time
            return self._success_result(result_content, execution_time)

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"SkillSubagent execution failed | id={self.subagent_id} | error={e}")
            return self._failure_result(e, execution_time)
        finally:
            _fork_depth.reset(depth_token)

    def _fork_depth_exceeded_result(self, depth: int) -> SkillResult:
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

    def _success_result(self, content: str, execution_time: float) -> SkillResult:
        return SkillResult(
            success=True,
            content=content,
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

    @staticmethod
    def _failure_result(error: Exception, execution_time: float) -> SkillResult:
        return SkillResult(
            success=False,
            error=str(error),
            execution_time=execution_time,
        )

    async def _execute_agent_run(
        self,
        user_message: str,
        system_prompt: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Execute through the unified agent loop, including zero-tool runs.

        Args:
            user_message: User's request
            system_prompt: System prompt
            context: Execution context

        Returns:
            Result content
        """
        if self._orchestrator_factory is None or self._agent_run_request_factory is None:
            raise RuntimeError(
                "SkillSubagent execution requires orchestrator_factory and "
                "agent_run_request_factory to be injected by the composition root."
            )

        if self._agent_orchestrator is None:
            self._agent_orchestrator = self._orchestrator_factory(
                llm_adapter=self.llm,
                tool_registry=self._tool_registry,
                skill_runner=None,
                tool_result_callback=None,
                permission_gateway_provider=self.permission_gateway_provider,
                active_model_provider=self._active_model_provider,
                scenario_llm_pool=self._scenario_llm_pool,
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

        # Execute with tools via the engine front door (ADR-0004 P4). The
        # headless AgentRunRequest is built by the injected factory so the
        # skills layer does not import the agent execution engine.
        result = await self._agent_orchestrator.run(
            self._agent_run_request_factory(
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
                execution_preset="skill_execution",
                execution_workspace=self._resolve_workspace(context),
            )
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
        script_path = _find_skill_script_path(self.skill.supporting_data, script_name)
        if script_path is None:
            return _script_not_found_result(script_name)

        _ensure_script_executable(script_path)

        logger.info(f"Executing script | skill={self.skill.name} | script={script_name}")

        try:
            return _script_run_result(_run_skill_script(script_path, args, timeout))
        except subprocess.TimeoutExpired:
            return _script_timeout_result(timeout)
        except Exception as e:
            return _script_error_result(e)

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
    tool_registry: ToolRegistryPort | None = None,
    orchestrator_factory: Callable[..., Any] | None = None,
    agent_run_request_factory: Callable[..., Any] | None = None,
    active_model_provider: Callable[..., Any] | None = None,
    scenario_llm_pool: Any | None = None,
) -> SkillSubagent:
    """
    Factory function to create a SkillSubagent.

    Args:
        skill: The skill content
        llm_adapter: LLM adapter
        tool_registry: The shared tool registry, injected by the caller.
        orchestrator_factory: Builds the unified agent orchestrator
            (injected by the composition root).
        agent_run_request_factory: Builds the headless engine run input
            (injected by the composition root).

    Returns:
        Configured SkillSubagent instance
    """
    allowed_tools = skill.frontmatter.allowed_tools
    return SkillSubagent(
        skill=skill,
        llm_adapter=llm_adapter,
        allowed_tools=allowed_tools,
        permission_gateway_provider=permission_gateway_provider,
        tool_registry=tool_registry,
        orchestrator_factory=orchestrator_factory,
        agent_run_request_factory=agent_run_request_factory,
        active_model_provider=active_model_provider,
        scenario_llm_pool=scenario_llm_pool,
    )


def _find_skill_script_path(
    supporting_data: Dict[str, Any],
    script_name: str,
) -> Path | None:
    for script in supporting_data.get("scripts", []):
        if script.get("name") != script_name:
            continue
        script_path = Path(script.get("path", ""))
        return script_path if script_path.exists() else None
    return None


def _ensure_script_executable(script_path: Path) -> None:
    if script_path.stat().st_mode & 0o111:
        return
    try:
        script_path.chmod(script_path.stat().st_mode | 0o111)
    except Exception as e:
        logger.warning(f"Could not make script executable: {e}")


def _run_skill_script(
    script_path: Path,
    args: List[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script_path)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(script_path.parent),
        **hidden_process_kwargs(),
    )


def _script_run_result(result: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode,
    }


def _script_not_found_result(script_name: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": f"Script not found: {script_name}",
        "stdout": "",
        "stderr": "",
        "return_code": -1,
    }


def _script_timeout_result(timeout: int) -> Dict[str, Any]:
    return {
        "success": False,
        "error": f"Script execution timed out after {timeout}s",
        "stdout": "",
        "stderr": "",
        "return_code": -1,
    }


def _script_error_result(error: Exception) -> Dict[str, Any]:
    return {
        "success": False,
        "error": str(error),
        "stdout": "",
        "stderr": "",
        "return_code": -1,
    }
