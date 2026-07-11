"""
Skill Runner - Execute skills with proper context

Implements the "Execute" phase of the skill system:
- Variable substitution ($argumentS, $0, $1, etc.)
- Context-based execution (direct or sub-agent via SkillSubagent)
- Tool access control via allowed-tools
- Script execution support
- Returns formatted SkillResult
"""
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Set

from ..utils.runtime import get_default_chat_workspace_path
from .schema import SkillContent, SkillResult
from .loader import SkillLoader
from .subagent import create_skill_subagent
from .tool_registry_port import ToolRegistryPort
from ..llm.base import LLMAdapter

logger = logging.getLogger(__name__)


class SkillRunner:
    """
    Skill Runner - Execute skills with proper context injection

    Handles the full execution lifecycle of a skill:
    1. Load the skill content
    2. Substitute variables
    3. Execute (direct or via sub-agent)
    4. Return formatted result
    """

    def __init__(
        self,
        loader: Optional[SkillLoader] = None,
        llm_adapter: Optional[LLMAdapter] = None,
        permission_gateway_provider: Callable[[], Any] | None = None,
        tool_registry: ToolRegistryPort | None = None,
        orchestrator_factory: Callable[..., Any] | None = None,
        engine_run_input_factory: Callable[..., Any] | None = None,
        active_model_provider: Callable[..., Any] | None = None,
        scenario_llm_pool: Any | None = None,
    ):
        """
        Initialize the skill runner.

        Args:
            loader: SkillLoader for loading skill content
            llm_adapter: LLM adapter for sub-agent execution
            tool_registry: The shared tool registry injected by the
                composition root; threaded to sub-agents so they can
                expose the registered tools.
            orchestrator_factory: Builds the function-calling orchestrator;
                injected by the composition root and threaded to sub-agents
                so the skills layer does not import the agent engine.
            engine_run_input_factory: Builds the headless engine run input;
                injected and threaded for the same reason.
        """
        self.loader = loader
        self.llm = llm_adapter
        self.permission_gateway_provider = permission_gateway_provider
        self._tool_registry = tool_registry
        self._orchestrator_factory = orchestrator_factory
        self._engine_run_input_factory = engine_run_input_factory
        self._active_model_provider = active_model_provider
        self._scenario_llm_pool = scenario_llm_pool

    async def execute(
        self,
        skill_name: str,
        arguments: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """
        Execute a skill

        Args:
            skill_name: Name of the skill to execute
            arguments: Command-line arguments passed to the skill
            context: Execution context (user_id, session_id, env_vars, etc.)

        Returns:
            SkillResult with execution outcome
        """
        start_time = time.time()
        arguments = arguments or []
        context = context or {}

        logger.info(f"Executing skill: {skill_name} with arguments: {arguments}")

        skill = self.loader.load_skill(skill_name)
        if not skill:
            return SkillResult(
                success=False,
                error=f"Skill not found: {skill_name}",
                execution_time=time.time() - start_time,
            )

        prompt = self._substitute_variables(
            skill.prompt_template,
            arguments,
            context,
        )

        try:
            if skill.frontmatter.context == "fork":
                result = await self._execute_with_subagent(skill, prompt, context)
            else:
                result = await self._execute_direct(skill, prompt, context)

            execution_time = time.time() - start_time
            result.execution_time = execution_time
            result.metadata["allowed_tools"] = skill.frontmatter.allowed_tools
            result.metadata["has_tool_restrictions"] = skill.frontmatter.allowed_tools is not None

            logger.info(
                f"Skill execution completed | "
                f"Skill: {skill_name} | "
                f"Success: {result.success} | "
                f"Time: {execution_time:.2f}s"
            )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Skill execution failed: {e}", exc_info=True)
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=execution_time,
            )

    def _substitute_variables(
        self,
        template: str,
        arguments: List[str],
        context: Dict[str, Any],
    ) -> str:
        """
        Substitute variables in the skill template

        Supported variables:
        - $argumentS or $@ - All arguments joined by spaces
        - $0, $1, $2, ... - Individual arguments by index
        - $# - Number of arguments
        - ${CLAUDE_session_id} - Session id from context
        - ${user_id} - User id from context
        - ${HOME} - User home directory
        - ${PWD} - Current working directory

        Args:
            template: Skill template with variables
            arguments: Command-line arguments
            context: Execution context

        Returns:
            Template with variables substituted
        """
        result = template
        workspace_root = self._resolve_workspace(context)

        all_args = " ".join(arguments)
        result = result.replace("$argumentS", all_args)
        result = result.replace("$@", all_args)
        result = result.replace("$#", str(len(arguments)))

        for i, arg in enumerate(arguments):
            result = result.replace(f"${i}", arg)

        env_vars = context.get("env_vars", {})
        for key, value in env_vars.items():
            result = result.replace(f"${{{key}}}", str(value))

        result = result.replace("${CLAUDE_session_id}", context.get("session_id", ""))
        result = result.replace("${user_id}", context.get("user_id", ""))
        result = result.replace("${HOME}", os.path.expanduser("~"))
        result = result.replace("${PWD}", workspace_root)

        return result

    def _resolve_workspace(self, context: Dict[str, Any]) -> str:
        env_vars = context.get("env_vars", {})
        raw_workspace = (
            str(context.get("workspace", "")).strip()
            or str(env_vars.get("PWD", "")).strip()
            or get_default_chat_workspace_path()
        )
        return os.path.realpath(os.path.expandvars(os.path.expanduser(raw_workspace)))

    async def _execute_direct(
        self,
        skill: SkillContent,
        prompt: str,
        context: Dict[str, Any],
    ) -> SkillResult:
        """
        Execute skill directly in current agent context

        This mode is for skills that provide instructions but don't
        require a separate agent execution context. The returned
        ``content`` becomes the tool-call result the model observes, so
        the SKILL.md body is injected as instructions the model then
        follows on subsequent iterations of the function-calling loop.

        Per the Claude Code Skills spec, the skill's declared
        ``allowed-tools`` is a *pre-approval* list — tool calls matching
        any entry skip the normal permission prompt; tools outside the
        list remain callable and go through the usual permission flow.
        We push the parsed rules onto a task-scoped contextvar so the
        permission gateway can short-circuit on a match. No explicit
        pop: the contextvar dies with the asyncio task that runs the
        turn.
        """
        _ = context
        allowed = skill.frontmatter.allowed_tools
        if allowed:
            from .active_restrictions import push_skill_rules

            push_skill_rules(allowed)

        prologue = ""
        if allowed:
            tool_list = ", ".join(allowed)
            prologue = (
                f"[skill={skill.name}] The following tool patterns are "
                f"pre-approved for this skill — calls matching them run "
                f"without asking for permission: {tool_list}. Other tools "
                f"remain available but will go through the normal "
                f"permission flow.\n\n"
            )

        return SkillResult(
            success=True,
            content=prologue + prompt,
            metadata={
                "mode": "direct",
                "skill_name": skill.name,
                "supporting_data": skill.supporting_data,
            },
        )

    async def _execute_with_subagent(
        self,
        skill: SkillContent,
        prompt: str,
        context: Dict[str, Any],
    ) -> SkillResult:
        """
        Execute skill using a dedicated SkillSubagent.

        Like the direct path, this pushes the skill's ``allowed-tools``
        rules onto the active pre-approval stack so subagent-originated
        tool calls matching the rules can skip the permission gateway
        prompt. Calls that don't match still pass through the gateway
        normally — pre-approval grants permission, it does not
        restrict.
        """
        if not self.llm:
            logger.warning("LLM adapter not available, falling back to direct mode")
            return await self._execute_direct(skill, prompt, context)

        allowed = skill.frontmatter.allowed_tools
        if allowed:
            from .active_restrictions import push_skill_rules

            push_skill_rules(allowed)

        subagent = create_skill_subagent(
            skill=skill,
            llm_adapter=self.llm,
            permission_gateway_provider=self.permission_gateway_provider,
            tool_registry=self._tool_registry,
            orchestrator_factory=self._orchestrator_factory,
            engine_run_input_factory=self._engine_run_input_factory,
            active_model_provider=self._active_model_provider,
            scenario_llm_pool=self._scenario_llm_pool,
        )
        user_message = context.get("user_message", "")

        logger.info(
            f"Executing skill via SkillSubagent | skill={skill.name} | "
            f"allowed_tools={skill.frontmatter.allowed_tools}"
        )

        try:
            result = await subagent.execute(
                user_message=user_message,
                system_prompt=prompt,
                context=context,
            )

            if result.metadata:
                result.metadata["scripts_available"] = subagent.get_script_names()

            return result

        except Exception as e:
            logger.error(f"Subagent execution failed: {e}")
            return SkillResult(
                success=False,
                error=f"Subagent execution failed: {e}",
            )

    def validate_skill_invocation(
        self,
        message: str,
    ) -> Optional[tuple[str, List[str]]]:
        """
        Check if a message is a skill invocation
        """
        if not message.startswith("/"):
            return None

        parts = message[1:].split()
        if not parts:
            return None

        skill_name = parts[0]
        arguments = parts[1:] if len(parts) > 1 else []

        return skill_name, arguments

    def get_allowed_tools(self, skill_name: str) -> Optional[Set[str]]:
        """
        Get the set of allowed tools for a skill.
        """
        if not self.loader:
            return None

        metadata = self.loader.indexer.get_metadata(skill_name)
        if not metadata:
            return None

        allowed = metadata.allowed_tools
        if allowed is None:
            return None

        return set(allowed)
