"""
工具注册表 - 完整实现
"""
from typing import Dict, List, Optional, Any
from .base import Tool, ToolSchema, ToolResult


class ToolRegistry:
    """
    工具注册表 - 管理可用工具

    职责：
    - 工具注册、查询、卸载
    - 工具执行
    - 权限控制
    """

    def __init__(self):
        """初始化工具注册表"""
        self._tools: Dict[str, Tool] = {}
        self._execution_stats: Dict[str, Dict] = {}

    def register(self, tool: Tool):
        """
        注册工具

        Args:
            tool: 工具实例
        """
        schema = tool.schema
        self._tools[schema.name] = tool
        self._execution_stats[schema.name] = {
            "call_count": 0,
            "success_count": 0,
            "error_count": 0,
        }

    def unregister(self, tool_name: str) -> bool:
        """
        卸载工具

        Args:
            tool_name: 工具名称

        Returns:
            是否成功卸载
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            del self._execution_stats[tool_name]
            return True
        return False

    def get(self, name: str) -> Optional[Tool]:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例或None
        """
        return self._tools.get(name)

    def list_tools(self, include_internal: bool = False) -> List[ToolSchema]:
        """
        列出所有可用工具

        Args:
            include_internal: 是否包含内部工具

        Returns:
            工具Schema列表
        """
        tools = []
        for tool in self._tools.values():
            schema = tool.schema
            # 如果不是内部工具，或者要求包含内部工具
            if not schema.internal or include_internal:
                tools.append(schema)
        return tools

    async def execute(
        self,
        name: str,
        params: dict,
    ) -> ToolResult:
        """
        执行工具

        Args:
            name: 工具名称
            params: 参数

        Returns:
            ToolResult: 执行结果
        """
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool not found: {name}"
            )

        # 更新统计
        stats = self._execution_stats[name]
        stats["call_count"] += 1

        try:
            # 执行工具
            result = await tool.execute(params)

            # 更新成功统计
            if result.success:
                stats["success_count"] += 1
            else:
                stats["error_count"] += 1

            return result

        except Exception as e:
            # 记录错误
            stats["error_count"] += 1
            return ToolResult(
                success=False,
                error=str(e)
            )

    def get_stats(self, tool_name: str) -> Optional[Dict]:
        """
        获取工具执行统计

        Args:
            tool_name: 工具名称

        Returns:
            统计信息或None
        """
        return self._execution_stats.get(tool_name)

    def get_all_stats(self) -> Dict[str, Dict]:
        """
        获取所有工具统计

        Returns:
            统计信息字典
        """
        return self._execution_stats.copy()


# ===== 内置工具示例 =====

class FileReadTool(Tool):
    """文件读取工具（示例）"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_read",
            description="读取文件内容",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径"
                    }
                },
                "required": ["path"]
            },
            permissions=["file.read"],
            internal=False,
        )

    async def execute(self, params: dict) -> ToolResult:
        """执行文件读取"""
        try:
            with open(params["path"], "r") as f:
                content = f.read()
            return ToolResult(success=True, data=content)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WebSearchTool(Tool):
    """Web搜索工具（示例）"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description="在网络上搜索信息",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大结果数",
                        "default": 5
                    }
                },
                "required": ["query"]
            },
            permissions=["network.request"],
            internal=False,
        )

    async def execute(self, params: dict) -> ToolResult:
        """执行Web搜索"""
        # 简化实现
        return ToolResult(
            success=True,
            data={"results": []}
        )
