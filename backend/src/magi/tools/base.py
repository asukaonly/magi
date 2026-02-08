"""
工具系统 - Tool基类和Schema定义
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum


class PermissionLevel(Enum):
    """工具权限级别"""
    SAFE = "safe"           # 安全：可自动执行
    CONFIRM = "confirm"      # 需确认：需要用户确认
    DANGER = "danger"       # 危险：默认拒绝


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class ToolSchema:
    """工具Schema（元数据）"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema格式
    permissions: List[str] = None
    internal: bool = False  # 是否为内部工具（不对用户可见）


class Tool(ABC):
    """
    工具基类

    所有工具必须继承此类并实现execute方法
    """

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """
        执行工具逻辑

        Args:
            params: 工具参数（根据schema验证）

        Returns:
            ToolResult: 执行结果
        """
        pass

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """
        返回工具的Schema

        Returns:
            ToolSchema: 工具元数据
        """
        pass
