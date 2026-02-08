"""
工具注册表 - 占位实现
"""
from typing import Dict, List, Optional, Any


class ToolRegistry:
    """工具注册表（临时占位）"""

    def __init__(self):
        self._tools: Dict[str, Any] = {}

    def register(self, tool):
        """注册工具"""
        self._tools[tool.name] = tool

    def get(self, name: str):
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self) -> List:
        """列出所有工具"""
        return list(self._tools.values())
