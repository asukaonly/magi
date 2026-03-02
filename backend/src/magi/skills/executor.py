"""
Skill Executor - Execute skills with proper context

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
from typing import Any, Dict, List, Optional, Set

from .schema import SkillContent, SkillFrontmatter, SkillResult
from .loader import SkillLoader
from .subagent import SkillSubagent, create_skill_subagent
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge

logger = logging.getLogger(__name__)


class SkillExecutor:
    """
    Skill Executor - Execute skills with proper context injection

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
    ):
        """
        initialize the Skill Executor

        Args:
            loader: SkillLoader for loading skill content
            llm_adapter: LLM adapter for sub-agent execution
        """
        self.loader = loader
        self.llm = llm_adapter

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

        # Load skill content
        skill = self.loader.load_skill(skill_name)
        if not skill:
            return SkillResult(
                success=False,
                error=f"Skill not found: {skill_name}",
                execution_time=time.time() - start_time,
            )

        # Substitute variables in the prompt template
        prompt = self._substitute_variables(
            skill.prompt_template,
            arguments,
            context,
        )

        # Execute based on context mode
        try:
            if skill.frontmatter.context == "fork":
                # Sub-agent execution
                result = await self._execute_with_subagent(skill, prompt, context)
            else:
                # Direct execution (current agent)
                result = await self._execute_direct(skill, prompt, context)

            execution_time = time.time() - start_time
            result.execution_time = execution_time

            # Include allowed_tools info in metadata
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

        # Substitute all arguments
        all_args = " ".join(arguments)
        result = result.replace("$argumentS", all_args)
        result = result.replace("$@", all_args)

        # Substitute argument count
        result = result.replace("$#", str(len(arguments)))

        # Substitute individual arguments
        for i, arg in enumerate(arguments):
            result = result.replace(f"${i}", arg)

        # Substitute environment variables from context
        env_vars = context.get("env_vars", {})
        for key, value in env_vars.items():
            result = result.replace(f"${{{key}}}", str(value))

        # Built-in variables
        result = result.replace("${CLAUDE_session_id}", context.get("session_id", ""))
        result = result.replace("${user_id}", context.get("user_id", ""))
        result = result.replace("${HOME}", os.path.expanduser("~"))
        result = result.replace("${PWD}", os.getcwd())

        return result

    async def _execute_direct(
        self,
        skill: SkillContent,
        prompt: str,
        context: Dict[str, Any],
    ) -> SkillResult:
        """
        Execute skill directly in current agent context

        This mode is for skills that provide instructions but don't
        require a separate agent execution context.

        Args:
            skill: The skill to execute
            prompt: processed prompt with variables substituted
            context: Execution context

        Returns:
            SkillResult with the prompt as the "content"
        """
        # In direct mode, the skill content IS the instructions
        # Return it for the caller to use
        return SkillResult(
            success=True,
            content=prompt,
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

        This creates an isolated execution context with:
        - Restricted tool access based on allowed_tools
        - Ability to execute scripts from scripts/ directory
        - Independent conversation context

        Args:
            skill: The skill to execute
            prompt: processed prompt with variables substituted
            context: Execution context

        Returns:
            SkillResult with sub-agent response
        """
        if not self.llm:
            logger.warning("LLM adapter not available, falling back to direct mode")
            return await self._execute_direct(skill, prompt, context)

        # Create the skill subagent with tool restrictions
        subagent = create_skill_subagent(
            skill=skill,
            llm_adapter=self.llm,
        )

        # Get user message from context
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

            # Add script execution capability info to metadata
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

        Parses messages in the form:
        - /skill-name
        - /skill-name arg1 arg2

        Args:
            message: User message to check

        Returns:
            Tuple of (skill_name, arguments) or None if not a skill invocation
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

        Args:
            skill_name: Name of the skill

        Returns:
            Set of allowed tool names, or None if no restriction
        """
        if not self.loader:
            return None

        metadata = self.loader.indexer.get_metadata(skill_name)
        if not metadata:
            return None

        allowed = metadata.allowed_tools
        if allowed is None:
            return None  # No restriction

        return set(allowed)

    def is_tool_allowed(self, skill_name: str, tool_name: str) -> bool:
        """
        Check if a tool is allowed for a specific skill.

        Args:
            skill_name: Name of the skill
            tool_name: Name of the tool to check

        Returns:
            True if the tool is allowed or no restriction exists
        """
        allowed_tools = self.get_allowed_tools(skill_name)

        # No restriction means all tools are allowed
        if allowed_tools is None:
            return True

        return tool_name in allowed_tools

    def filter_tools_for_skill(
        self,
        skill_name: str,
        available_tools: List[str],
    ) -> List[str]:
        """
        Filter available tools based on skill's allowed-tools restriction.

        Args:
            skill_name: Name of the skill
            available_tools: List of all available tool names

        Returns:
            Filtered list of tool names allowed for this skill
        """
        allowed_tools = self.get_allowed_tools(skill_name)

        # No restriction means all tools are allowed
        if allowed_tools is None:
            return available_tools

        return [t for t in available_tools if t in allowed_tools]

    async def execute_script(
        self,
        skill_name: str,
        script_name: str,
        args: Optional[List[str]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Execute a script from a skill's scripts/ directory.

        Args:
            skill_name: Name of the skill
            script_name: Name of the script file
            args: Arguments to pass to the script
            timeout: Execution timeout in seconds

        Returns:
            Dict with stdout, stderr, return_code, success
        """
        if not self.loader:
            return {
                "success": False,
                "error": "SkillLoader not available",
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }

        # Load the skill
        skill = self.loader.load_skill(skill_name)
        if not skill:
            return {
                "success": False,
                "error": f"Skill not found: {skill_name}",
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }

        # Create subagent for script execution
        if not self.llm:
            return {
                "success": False,
                "error": "LLM adapter not available",
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }

        subagent = create_skill_subagent(skill, self.llm)
        return await subagent.execute_script(script_name, args, timeout)

    def get_available_scripts(self, skill_name: str) -> List[str]:
        """
        Get list of available scripts for a skill.

        Args:
            skill_name: Name of the skill

        Returns:
            List of script filenames
        """
        if not self.loader:
            return []

        skill = self.loader.load_skill(skill_name)
        if not skill:
            return []

        scripts = skill.supporting_data.get("scripts", [])
        return [s.get("name") for s in scripts if s.get("name")]
