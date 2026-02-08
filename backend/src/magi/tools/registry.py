"""
工具注册表

实现工具的注册、查询、执行、监控等功能
"""
import asyncio
import time
from typing import Dict, List, Optional, Any, Type
from collections import defaultdict
import logging

from .schema import Tool, ToolSchema, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class ToolExecutionStats:
    """工具执行统计"""

    def __init__(self):
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.total_execution_time: float = 0.0
        self.last_execution_time: Optional[float] = None
        self.average_execution_time: float = 0.0

    def record_call(self, success: bool, execution_time: float):
        """记录一次调用"""
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
        """获取统计信息"""
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
    工具注册表

    管理工具的注册、查询、执行、统计等功能
    """

    def __init__(self):
        # 工具注册 {name: tool_class}
        self._tools: Dict[str, Type[Tool]] = {}

        # 工具实例缓存 {name: instance}
        self._tool_instances: Dict[str, Tool] = {}

        # 工具类别索引 {category: [tool_names]}
        self._category_index: Dict[str, List[str]] = defaultdict(list)

        # 工具标签索引 {tag: [tool_names]}
        self._tag_index: Dict[str, List[str]] = defaultdict(list)

        # 执行统计 {tool_name: ToolExecutionStats}
        self._stats: Dict[str, ToolExecutionStats] = defaultdict(ToolExecutionStats)

    def register(self, tool_class: Type[Tool]) -> None:
        """
        注册工具

        Args:
            tool_class: 工具类
        """
        # 创建临时实例获取schema
        temp_instance = tool_class()
        schema = temp_instance.get_schema()

        if not schema:
            raise ValueError(f"Tool {tool_class.__name__} must define a schema")

        tool_name = schema.name

        # 检查是否已注册
        if tool_name in self._tools:
            logger.warning(f"Tool {tool_name} already registered, overwriting")

        # 注册工具类
        self._tools[tool_name] = tool_class

        # 创建并缓存实例
        self._tool_instances[tool_name] = temp_instance

        # 更新索引
        self._category_index[schema.category].append(tool_name)

        for tag in schema.tags:
            self._tag_index[tag].append(tool_name)

        # 初始化统计
        self._stats[tool_name] = ToolExecutionStats()

        logger.info(f"Registered tool: {tool_name} (category: {schema.category})")

    def unregister(self, tool_name: str) -> bool:
        """
        注销工具

        Args:
            tool_name: 工具名称

        Returns:
            是否成功
        """
        if tool_name not in self._tools:
            logger.warning(f"Tool {tool_name} not registered")
            return False

        # 获取schema
        schema = self._tool_instances[tool_name].get_schema()

        # 从索引中移除
        if schema.category in self._category_index:
            self._category_index[schema.category].remove(tool_name)

        for tag in schema.tags:
            if tag in self._tag_index:
                self._tag_index[tag].remove(tool_name)

        # 删除工具
        del self._tools[tool_name]
        del self._tool_instances[tool_name]
        del self._stats[tool_name]

        logger.info(f"Unregistered tool: {tool_name}")
        return True

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """
        获取工具实例

        Args:
            tool_name: 工具名称

        Returns:
            工具实例或None
        """
        return self._tool_instances.get(tool_name)

    def list_tools(
        self,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[str]:
        """
        列出工具

        Args:
            category: 过滤类别
            tags: 过滤标签

        Returns:
            工具名称列表
        """
        tools = list(self._tools.keys())

        # 按类别过滤
        if category:
            tools = list(set(tools) & set(self._category_index.get(category, [])))

        # 按标签过滤
        if tags:
            tag_sets = [set(self._tag_index.get(tag, [])) for tag in tags]
            if tag_sets:
                tools = list(set(tools) & set.intersection(*tag_sets))

        return tools

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        获取工具信息

        Args:
            tool_name: 工具名称

        Returns:
            工具信息或None
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return None

        info = tool.get_info()
        info["stats"] = self._stats[tool_name].get_stats()

        return info

    def get_all_tools_info(self) -> List[Dict[str, Any]]:
        """
        获取所有工具信息

        Returns:
            工具信息列表
        """
        return [
            self.get_tool_info(tool_name)
            for tool_name in self._tools.keys()
        ]

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        执行工具

        Args:
            tool_name: 工具名称
            parameters: 参数
            context: 执行上下文

        Returns:
            执行结果
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

        # 验证参数
        valid, error_msg = await tool.validate_parameters(parameters)
        if not valid:
            return ToolResult(
                success=False,
                error=error_msg,
                error_code="INVALID_PARAMETERS"
            )

        # 执行工具
        start_time = time.time()
        try:
            # 设置超时
            result = await asyncio.wait_for(
                tool.execute(parameters, context),
                timeout=schema.timeout
            )

            execution_time = time.time() - start_time

            # 记录统计
            stats.record_call(result.success, execution_time)

            # 执行后钩子
            result = await tool.after_execution(result, context)

            return result

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            return ToolResult(
                success=False,
                error=f"Tool execution timeout after {schema.timeout}s",
                error_code="TIMEOUT",
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            logger.exception(f"Tool {tool_name} execution failed")

            return ToolResult(
                success=False,
                error=str(e),
                error_code="EXECUTION_ERROR",
                execution_time=execution_time
            )

    async def execute_batch(
        self,
        commands: List[Dict[str, Any]],
        context: ToolExecutionContext,
        parallel: bool = False
    ) -> List[ToolResult]:
        """
        批量执行工具

        Args:
            commands: 命令列表 [{"tool": name, "parameters": {...}}, ...]
            context: 执行上下文
            parallel: 是否并行执行

        Returns:
            结果列表
        """
        if parallel:
            # 并行执行
            tasks = [
                self.execute(cmd["tool"], cmd.get("parameters", {}), context)
                for cmd in commands
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        else:
            # 串行执行
            results = []
            for cmd in commands:
                result = await self.execute(
                    cmd["tool"],
                    cmd.get("parameters", {}),
                    context
                )
                results.append(result)

                # 如果失败且不要求继续，停止执行
                if not result.success:
                    break

            return results

    def get_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取统计信息

        Args:
            tool_name: 工具名称（None表示获取所有）

        Returns:
            统计信息
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


# 全局工具注册表实例
tool_registry = ToolRegistry()
