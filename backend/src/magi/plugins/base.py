"""
插件系统 - Plugin基类和生命周期钩子
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict
from enum import Enum


class PluginType(Enum):
    """插件类型"""
    TOOL = "tool"           # 工具插件
    STORAGE = "storage"     # 存储插件
    LLM = "llm"            # LLM适配器插件
    SENSOR = "sensor"       # 传感器插件


class Plugin(ABC):
    """
    插件基类

    插件可以通过生命周期钩子（AOP风格）介入Agent执行流程：
    - before_sense / after_sense
    - before_plan / after_plan
    - before_act / after_act

    插件也可以提供扩展：
    - Tools（工具）
    - StorageBackend（存储后端）
    - LLMAdapter（LLM适配器）
    - Sensors（传感器）
    """

    def __init__(self):
        self._enabled = True
        self._priority = 0  # 优先级（数字越大越先执行）

    @property
    def name(self) -> str:
        """插件名称"""
        return self.__class__.__name__

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    @property
    def priority(self) -> int:
        """优先级"""
        return self._priority

    @priority.setter
    def priority(self, value: int):
        self._priority = value

    @property
    def version(self) -> str:
        """插件版本"""
        return "1.0.0"

    # ===== 生命周期钩子 =====

    async def before_sense(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Sense阶段前的钩子（Chain模式 - 顺序执行）

        Args:
            context: 上下文信息

        Returns:
            可选的修改后的上下文（返回None则终止后续钩子）
        """
        pass

    async def after_sense(self, perceptions: List) -> List:
        """
        Sense阶段后的钩子（Parallel模式 - 并发执行）

        Args:
            perceptions: 感知列表

        Returns:
            可选的修改后的感知列表
        """
        return perceptions

    async def before_plan(self, perception) -> Optional[Any]:
        """
        Plan阶段前的钩子（Chain模式）

        Args:
            perception: 感知输入

        Returns:
            可选的修改后的感知（返回None则不执行Plan）
        """
        pass

    async def after_plan(self, action) -> Any:
        """
        Plan阶段后的钩子（Parallel模式）

        Args:
            action: 行动计划

        Returns:
            可选的修改后的行动
        """
        return action

    async def before_act(self, action) -> Optional[Any]:
        """
        Act阶段前的钩子（Chain模式）

        Args:
            action: 要执行的动作

        Returns:
            可选的修改后的动作（返回None则不执行Act）
        """
        pass

    async def after_act(self, result) -> Any:
        """
        Act阶段后的钩子（Parallel模式）

        Args:
            result: 执行结果

        Returns:
            可选的修改后的结果
        """
        return result

    # ===== 扩展点 =====

    def get_tools(self) -> List:
        """
        获取插件提供的工具

        Returns:
            工具列表
        """
        return []

    def get_storage_backend(self):
        """
        获取插件提供的存储后端

        Returns:
            存储后端实例或None
        """
        return None

    def get_llm_adapter(self):
        """
        获取插件提供的LLM适配器

        Returns:
            LLM适配器实例或None
        """
        return None

    def get_sensors(self) -> List:
        """
        获取插件提供的传感器

        Returns:
            传感器列表
        """
        return []
