"""
Tool registry.

Provides tool registration, lookup, execution, and monitoring.
"""
import asyncio
import time
from typing import Dict, List, Optional, Any, Type, TYPE_CHECKING
from collections import defaultdict
import logging

from .schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolErrorCode

# Avoid circular import
if TYPE_CHECKING:
    from ..skills.schema import SkillMetadata

logger = logging.getLogger(__name__)


class ToolExecutionStats:
    """Tool execution statistics."""

    def __init__(self):
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.total_execution_time: float = 0.0
        self.last_execution_time: Optional[float] = None
        self.average_execution_time: float = 0.0

    def record_call(self, success: bool, execution_time: float) -> None:
        """Record a single tool call."""
        self.total_calls += 1
        self.last_execution_time = execution_time

        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1

        self.total_execution_time += execution_time
        if self.total_calls > 0:
            self.average_execution_time = self.total_execution_time / self.total_calls

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics summary."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": self.successful_calls / self.total_calls if self.total_calls > 0 else 0,
            "average_execution_time": self.average_execution_time,
            "last_execution_time": self.last_execution_time,
        }


class ToolRegistry:
    """
    Tool registry.

    Manages tool registration, lookup, execution, and statistics.
    """

    def __init__(self, skill_indexer=None):
        # Tool registry: {name: tool_class}
        self._tools: Dict[str, type[Tool]] = {}

        # Tool instance cache: {name: instance}
        self._tool_instances: Dict[str, Tool] = {}

        # Category index: {category: [tool_names]}
        self._category_index: Dict[str, List[str]] = defaultdict(list)

        # Tag index: {tag: [tool_names]}
        self._tag_index: Dict[str, List[str]] = defaultdict(list)

        # Execution stats: {tool_name: ToolExecutionStats}
        self._stats: Dict[str, ToolExecutionStats] = defaultdict(ToolExecutionStats)

        # Skills index: {name: SkillMetadata}, lazy-loaded, metadata only
        self._skills: Dict[str, "SkillMetadata"] = {}

        # Skill indexer instance
        self._skill_indexer = skill_indexer

    def register(self, tool_class: type[Tool]) -> None:
        """
        Register a tool.

        Args:
            tool_class: Tool class to register.
        """
        # Create temporary instance to get schema
        temp_instance = tool_class()
        schema = temp_instance.get_schema()

        if not schema:
            raise ValueError(f"Tool {tool_class.__name__} must define a schema")

        tool_name = schema.name

        # Check if already registered
        if tool_name in self._tools:
            logger.warning(f"Tool {tool_name} already registered, overwriting")

        # Register tool class
        self._tools[tool_name] = tool_class

        # Create and cache instance
        self._tool_instances[tool_name] = temp_instance

        # Update indexes
        self._category_index[schema.category].append(tool_name)

        for tag in schema.tags:
            self._tag_index[tag].append(tool_name)

        # Initialize statistics
        self._stats[tool_name] = ToolExecutionStats()

        logger.info(f"Registered tool: {tool_name} (category: {schema.category})")

    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool.

        Args:
            tool_name: Tool name.

        Returns:
            True if successful.
        """
        if tool_name not in self._tools:
            logger.warning(f"Tool {tool_name} not registered")
            return False

        # Get schema
        schema = self._tool_instances[tool_name].get_schema()

        # Remove from indexes
        if schema.category in self._category_index:
            self._category_index[schema.category].remove(tool_name)

        for tag in schema.tags:
            if tag in self._tag_index:
                self._tag_index[tag].remove(tool_name)

        # Delete tool
        del self._tools[tool_name]
        del self._tool_instances[tool_name]
        del self._stats[tool_name]

        logger.info(f"Unregistered tool: {tool_name}")
        return True

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """
        Get tool instance.

        Args:
            tool_name: Tool name.

        Returns:
            Tool instance or None.
        """
        return self._tool_instances.get(tool_name)

    def list_tools(
        self,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[str]:
        """
        List tools with optional filters.

        Args:
            category: Filter by category.
            tags: Filter by tags.

        Returns:
            List of tool names.
        """
        tools = list(self._tools.keys())

        # Filter by category
        if category:
            tools = list(set(tools) & set(self._category_index.get(category, [])))

        # Filter by tags
        if tags:
            tag_sets = [set(self._tag_index.get(tag, [])) for tag in tags]
            if tag_sets:
                tools = list(set(tools) & set.intersection(*tag_sets))

        return tools

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get tool info.

        Args:
            tool_name: Tool name.

        Returns:
            Tool info dict or None.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return None

        info = tool.get_info()
        info["stats"] = self._stats[tool_name].get_stats()

        return info

    def get_all_tools_info(self) -> List[Dict[str, Any]]:
        """
        Get all tool info (includes skills).

        Returns:
            List of tool info dicts.
        """
        tools_info = [
            self.get_tool_info(tool_name)
            for tool_name in self._tools.keys()
        ]

        # Add skills info (metadata only)
        for skill_name, skill_metadata in self._skills.items():
            tools_info.append({
                "name": skill_metadata.name,
                "description": skill_metadata.description,
                "category": skill_metadata.category or "skill",
                "type": "skill",
                "argument_hint": skill_metadata.argument_hint,
                "user_invocable": skill_metadata.user_invocable,
                "context": skill_metadata.context,
                "agent": skill_metadata.agent,
                "tags": skill_metadata.tags,
                "parameters": [],
                "examples": [],
            })

        return tools_info

    def register_skill_index(self, skills: Dict[str, "SkillMetadata"]) -> None:
        """
        register Skill index

        Args:
            skills: {name: SkillMetadata} dictionary
        """
        self._skills = dict(skills)
        logger.info(f"Registered {len(skills)} skills to registry")

    def bind_skill_indexer(self, skill_indexer) -> None:
        """Bind the skill indexer used for refresh operations."""
        self._skill_indexer = skill_indexer

    def get_skill_names(self) -> List[str]:
        """
        Get all registered skill names.

        Returns:
            List of skill names.
        """
        return list(self._skills.keys())

    def get_skill_metadata(self, name: str) -> Optional["SkillMetadata"]:
        """
        Get skill metadata by name.

        Args:
            name: Skill name.

        Returns:
            SkillMetadata or None.
        """
        return self._skills.get(name)

    def is_skill(self, name: str) -> bool:
        """
        Check if name is a skill.

        Args:
            name: Tool or skill name.

        Returns:
            True if it is a skill.
        """
        return name in self._skills

    def refresh_skills(self) -> Dict[str, "SkillMetadata"]:
        """
        Refresh skills index.

        Returns:
            Updated skills dictionary.
        """
        if self._skill_indexer:
            skills = self._skill_indexer.refresh()
            self._skills = skills
            return skills
        return {}

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Execute a tool.

        Args:
            tool_name: Tool name.
            parameters: Tool parameters.
            context: Execution context.

        Returns:
            Execution result.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} not found",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value
            )

        schema = tool.get_schema()
        stats = self._stats[tool_name]

        # Permission check
        if schema.dangerous and "dangerous_tools" not in context.permissions:
            logger.warning(f"Tool {tool_name} requires dangerous_tools permission")
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} requires 'dangerous_tools' permission",
                error_code=ToolErrorCode.PERMISSION_DENIED.value
            )

        # Check authentication requirement
        if schema.requires_auth and "authenticated" not in context.permissions:
            logger.warning(f"Tool {tool_name} requires authentication")
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} requires authentication",
                error_code=ToolErrorCode.AUTH_REQUIRED.value
            )

        # Check role permission
        if schema.allowed_roles:
            agent_role = context.env_vars.get("role", "guest")
            if agent_role not in schema.allowed_roles:
                logger.warning(f"Tool {tool_name} requires one of roles: {schema.allowed_roles}")
                return ToolResult(
                    success=False,
                    error=f"Tool {tool_name} requires one of roles: {schema.allowed_roles}",
                    error_code=ToolErrorCode.ROLE_NOT_ALLOWED.value
                )

        # Validate parameters
        valid, error_msg = await tool.validate_parameters(parameters)
        if not valid:
            return ToolResult(
                success=False,
                error=error_msg,
                error_code=ToolErrorCode.INVALID_PARAMETERS.value
            )

        # Execute tool
        start_time = time.time()
        try:
            # Set timeout
            result = await asyncio.wait_for(
                tool.execute(parameters, context),
                timeout=schema.timeout
            )

            execution_time = time.time() - start_time

            # Record statistics
            stats.record_call(result.success, execution_time)

            # Post-execution hook
            result = await tool.after_execution(result, context)

            return result

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            return ToolResult(
                success=False,
                error=f"Tool execution timeout after {schema.timeout}s",
                error_code=ToolErrorCode.TIMEOUT.value,
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            logger.exception(f"Tool {tool_name} execution failed")

            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                execution_time=execution_time
            )

    async def execute_batch(
        self,
        commands: List[Dict[str, Any]],
        context: ToolExecutionContext,
        parallel: bool = False
    ) -> List[ToolResult]:
        """
        Execute multiple tools in batch.

        Args:
            commands: Command list [{"tool": name, "parameters": {...}}, ...].
            context: Execution context.
            parallel: Whether to execute in parallel.

        Returns:
            List of results.
        """
        if parallel:
            # Execute in parallel
            tasks = [
                self.execute(cmd["tool"], cmd.get("parameters", {}), context)
                for cmd in commands
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        else:
            # Execute serially
            results = []
            for cmd in commands:
                result = await self.execute(
                    cmd["tool"],
                    cmd.get("parameters", {}),
                    context
                )
                results.append(result                )

                # Stop on failure if requested
                if not result.success:
                    break

            return results

    def get_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get execution statistics.

        Args:
            tool_name: Tool name (None to get all).

        Returns:
            Statistics dictionary.
        """
        if tool_name:
            if tool_name in self._stats:
                return {
                    tool_name: self._stats[tool_name].get_stats()
                }
            return {}
        else:
            return {
                name: stats.get_stats()
                for name, stats in self._stats.items()
            }

    def export_to_claude_format(self) -> List[Dict[str, Any]]:
        """
        Export all tools in Claude Tool Use API format.

        Only exports tools that are ready (have required configuration).

        Returns:
            List of tools in Claude API format.
        """
        tools = []
        for tool_name in self._tools.keys():
            tool = self.get_tool(tool_name)
            if tool and tool.is_ready():
                tools.append(tool.to_claude_format())
            elif tool and not tool.is_ready():
                logger.debug(f"Tool {tool_name} not ready (missing configuration), skipping")
        return tools

    def import_from_claude_format(
        self,
        tool_defs: List[Dict[str, Any]],
        executor: callable
    ) -> None:
        """
        Import tools from Claude Tool Use API format.

        Args:
            tool_defs: List of tool definitions in Claude format.
            executor: Execute function with signature async def execute(name, params) -> Any.
        """
        from .builtin import DynamicTool

        for tool_def in tool_defs:
            schema = Tool.Schema.from_claude_format(tool_def)

            # Create dynamic tool class
            dynamic_tool = type(
                f"ClaudeTool_{tool_def['name']}",
                (DynamicTool,),
                {
                    "schema": schema,
                    "_executor": staticmethod(executor),
                }
            )

            try:
                self.register(dynamic_tool)
            except Exception as e:
                logger.error(f"Failed to import tool {tool_def.get('name')}: {e}")


# Global tool registry instance
tool_registry = ToolRegistry()
