"""
toolRegistry

Implementationtool的register、query、Execute、monitor等function
"""
import asyncio
import time
from typing import Dict, List, Optional, Any, type, type_checkING
from collections import defaultdict
import logging

from .schema import Tool, ToolSchema, ToolExecutionContext, ToolResult

# Avoid circular import
if type_checkING:
    from ..skills.schema import Skillmetadata

logger = logging.getLogger(__name__)


class ToolExecutionStats:
    """toolExecutestatistics"""

    def __init__(self):
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.total_execution_time: float = 0.0
        self.last_execution_time: Optional[float] = None
        self.average_execution_time: float = 0.0

    def record_call(self, success: bool, execution_time: float):
        """record一次调用"""
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
        """getstatisticsinfo"""
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
    toolRegistry

    管理tool的register、query、Execute、statistics等function
    """

    def __init__(self, skill_indexer=None):
        # toolregister {name: tool_class}
        self._tools: Dict[str, type[Tool]] = {}

        # toolInstancecache {name: instance}
        self._tool_instances: Dict[str, Tool] = {}

        # toolClass别index {category: [tool_names]}
        self._category_index: Dict[str, List[str]] = defaultdict(list)

        # toollabelindex {tag: [tool_names]}
        self._tag_index: Dict[str, List[str]] = defaultdict(list)

        # Executestatistics {tool_name: ToolExecutionStats}
        self._stats: Dict[str, ToolExecutionStats] = defaultdict(ToolExecutionStats)

        # Skills index {name: Skillmetadata} - 按需load，仅storagemetadata
        self._skills: Dict[str, "Skillmetadata"] = {}

        # Skill indexer Instance
        self._skill_indexer = skill_indexer

    def register(self, tool_class: type[Tool]) -> None:
        """
        registertool

        Args:
            tool_class: toolClass
        """
        # createtemporaryInstancegetschema
        temp_instance = tool_class()
        schema = temp_instance.get_schema()

        if not schema:
            raise Valueerror(f"Tool {tool_class.__name__} must define a schema")

        tool_name = schema.name

        # checkis notregistered
        if tool_name in self._tools:
            logger.warning(f"Tool {tool_name} already registered, overwriting")

        # registertoolClass
        self._tools[tool_name] = tool_class

        # create并cacheInstance
        self._tool_instances[tool_name] = temp_instance

        # updateindex
        self._category_index[schema.category].append(tool_name)

        for tag in schema.tags:
            self._tag_index[tag].append(tool_name)

        # initializestatistics
        self._stats[tool_name] = ToolExecutionStats()

        logger.info(f"Registered tool: {tool_name} (category: {schema.category})")

    def unregister(self, tool_name: str) -> bool:
        """
        deregistertool

        Args:
            tool_name: toolName

        Returns:
            is notsuccess
        """
        if tool_name not in self._tools:
            logger.warning(f"Tool {tool_name} not registered")
            return False

        # getschema
        schema = self._tool_instances[tool_name].get_schema()

        # 从index中Remove
        if schema.category in self._category_index:
            self._category_index[schema.category].remove(tool_name)

        for tag in schema.tags:
            if tag in self._tag_index:
                self._tag_index[tag].remove(tool_name)

        # deletetool
        del self._tools[tool_name]
        del self._tool_instances[tool_name]
        del self._stats[tool_name]

        logger.info(f"Unregistered tool: {tool_name}")
        return True

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """
        gettoolInstance

        Args:
            tool_name: toolName

        Returns:
            toolInstance或None
        """
        return self._tool_instances.get(tool_name)

    def list_tools(
        self,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[str]:
        """
        column出tool

        Args:
            category: filterClass别
            tags: filterlabel

        Returns:
            toolNamelist
        """
        tools = list(self._tools.keys())

        # 按Class别filter
        if category:
            tools = list(set(tools) & set(self._category_index.get(category, [])))

        # 按labelfilter
        if tags:
            tag_sets = [set(self._tag_index.get(tag, [])) for tag in tags]
            if tag_sets:
                tools = list(set(tools) & set.intersection(*tag_sets))

        return tools

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        gettoolinfo

        Args:
            tool_name: toolName

        Returns:
            toolinfo或None
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return None

        info = tool.get_info()
        info["stats"] = self._stats[tool_name].get_stats()

        return info

    def get_all_tools_info(self) -> List[Dict[str, Any]]:
        """
        getalltoolinfo（contains Skills）

        Returns:
            toolinfolist
        """
        tools_info = [
            self.get_tool_info(tool_name)
            for tool_name in self._tools.keys()
        ]

        # add Skills info（仅metadata）
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

    def register_skill_index(self, skills: Dict[str, "Skillmetadata"]) -> None:
        """
        register Skill index

        Args:
            skills: {name: Skillmetadata} dictionary
        """
        self._skills.update(skills)
        logger.info(f"Registered {len(skills)} skills to registry")

    def get_skill_names(self) -> List[str]:
        """
        getallregistered的 Skill Name

        Returns:
            Skill Namelist
        """
        return list(self._skills.keys())

    def get_skill_metadata(self, name: str) -> Optional["Skillmetadata"]:
        """
        get指定 Skill 的metadata

        Args:
            name: Skill Name

        Returns:
            Skillmetadata 或 None
        """
        return self._skills.get(name)

    def is_skill(self, name: str) -> bool:
        """
        check指定Nameis not为 Skill

        Args:
            name: tool/Skill Name

        Returns:
            is not为 Skill
        """
        return name in self._skills

    def refresh_skills(self) -> Dict[str, "Skillmetadata"]:
        """
        刷new Skills index

        Returns:
            update后的 Skills dictionary
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
        Executetool

        Args:
            tool_name: toolName
            parameters: Parameter
            context: Executecontext

        Returns:
            Execution result
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} not found",
                error_code="TOOL_NOT_FOUND"
            )

        schema = tool.get_schema()
        stats = self._stats[tool_name]

        # permissioncheck
        if schema.dangerous and "dangerous_tools" not in context.permissions:
            logger.warning(f"Tool {tool_name} requires dangerous_tools permission")
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} requires 'dangerous_tools' permission",
                error_code="permission_DENIED"
            )

        # checkauthentication要求
        if schema.requires_auth and "authenticated" not in context.permissions:
            logger.warning(f"Tool {tool_name} requires authentication")
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} requires authentication",
                error_code="AUTH_REQUIRED"
            )

        # checkrolepermission
        if schema.allowed_roles:
            agent_role = context.env_vars.get("role", "guest")
            if agent_role not in schema.allowed_roles:
                logger.warning(f"Tool {tool_name} requires one of roles: {schema.allowed_roles}")
                return ToolResult(
                    success=False,
                    error=f"Tool {tool_name} requires one of roles: {schema.allowed_roles}",
                    error_code="role_NOT_allowED"
                )

        # ValidateParameter
        valid, error_msg = await tool.validate_parameters(parameters)
        if not valid:
            return ToolResult(
                success=False,
                error=error_msg,
                error_code="INVALid_parameterS"
            )

        # Executetool
        start_time = time.time()
        try:
            # Settingtimeout
            result = await asyncio.wait_for(
                tool.execute(parameters, context),
                timeout=schema.timeout
            )

            execution_time = time.time() - start_time

            # recordstatistics
            stats.record_call(result.success, execution_time)

            # Execute后钩子
            result = await tool.after_execution(result, context)

            return result

        except asyncio.Timeouterror:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            return ToolResult(
                success=False,
                error=f"Tool execution timeout after {schema.timeout}s",
                error_code="timeout",
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            logger.exception(f"Tool {tool_name} execution failed")

            return ToolResult(
                success=False,
                error=str(e),
                error_code="EXECUTION_error",
                execution_time=execution_time
            )

    async def execute_batch(
        self,
        commands: List[Dict[str, Any]],
        context: ToolExecutionContext,
        parallel: bool = False
    ) -> List[ToolResult]:
        """
        批量Executetool

        Args:
            commands: commandlist [{"tool": name, "parameters": {...}}, ...]
            context: Executecontext
            parallel: is notparallelExecute

        Returns:
            Resultlist
        """
        if parallel:
            # parallelExecute
            tasks = [
                self.execute(cmd["tool"], cmd.get("parameters", {}), context)
                for cmd in commands
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        else:
            # serialExecute
            results = []
            for cmd in commands:
                result = await self.execute(
                    cmd["tool"],
                    cmd.get("parameters", {}),
                    context
                )
                results.append(result)

                # 如果failure且不要求继续，stopExecute
                if not result.success:
                    break

            return results

    def get_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        getstatisticsinfo

        Args:
            tool_name: toolName（Nonetable示getall）

        Returns:
            statisticsinfo
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
        exportalltool为 Claude Tool Use API format

        Returns:
            Claude tools API format的toollist
        """
        tools = []
        for tool_name in self._tools.keys():
            tool = self.get_tool(tool_name)
            if tool:
                tools.append(tool.to_claude_format())
        return tools

    def import_from_claude_format(
        self,
        tool_defs: List[Dict[str, Any]],
        executor: callable
    ) -> None:
        """
        从 Claude Tool Use API formatimporttool

        Args:
            tool_defs: Claude format的tool定义list
            executor: ExecuteFunction，signature为 async def execute(name, params) -> Any
        """
        from .builtin import DynamicTool

        for tool_def in tool_defs:
            schema = Tool.Schema.from_claude_format(tool_def)

            # createdynamictoolClass
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


# globaltoolRegistryInstance
tool_registry = ToolRegistry()
