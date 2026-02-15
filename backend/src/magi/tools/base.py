"""
tool系统 - ToolBase classandSchema定义
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum


class Permissionlevel(Enum):
    """toolpermissionlevel"""
    safe = "safe"           # safe：可自动Execute
    confirm = "confirm"      # 需确认：需要user确认
    DANGER = "danger"       # dangerous：default拒绝


@dataclass
class ToolResult:
    """toolExecution result"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class ToolSchema:
    """toolSchema（metadata）"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schemaformat
    permissions: List[str] = None
    internal: bool = False  # is notttt为internaltool（不对user可见）


class Tool(ABC):
    """
    toolBase class

    alltool必须继承此Class并ImplementationexecuteMethod
    """

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """
        Executetool逻辑

        Args:
            params: toolParameter（根据schemaValidate）

        Returns:
            ToolResult: Execution result
        """
        pass

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """
        Returntool的Schema

        Returns:
            ToolSchema: toolmetadata
        """
        pass
