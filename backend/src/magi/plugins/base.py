"""
plugin系统 - PluginBase classand生命period钩子
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict
from enum import Enum


class Plugintype(Enum):
    """plugintype"""
    TOOL = "tool"           # toolplugin
    STORAGE = "storage"     # storageplugin
    LLM = "llm"            # LLMAdapterplugin
    SENSOR = "sensor"       # 传感器plugin


class Plugin(ABC):
    """
    pluginBase class

    plugin可以通过生命period钩子（AOPstyle）介入AgentExecuteprocess：
    - before_sense / after_sense
    - before_plan / after_plan
    - before_act / after_act

    plugin也可以提供extension：
    - Tools（tool）
    - StorageBackend（storage后端）
    - LLMAdapter（LLMAdapter）
    - Sensors（传感器）
    """

    def __init__(self):
        self._enabled = True
        self._priority = 0  # priority（number越大越先Execute）

    @property
    def name(self) -> str:
        """pluginName"""
        return self.__class__.__name__

    @property
    def enabled(self) -> bool:
        """is notEnable"""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    @property
    def priority(self) -> int:
        """priority"""
        return self._priority

    @priority.setter
    def priority(self, value: int):
        self._priority = value

    @property
    def version(self) -> str:
        """pluginversion"""
        return "1.0.0"

    # ===== 生命period钩子 =====

    async def before_sense(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Sense阶段前的钩子（chainpattern - 顺序Execute）

        Args:
            context: contextinfo

        Returns:
            optional的修改后的context（ReturnNone则终止后续钩子）
        """
        pass

    async def after_sense(self, perceptions: List) -> List:
        """
        Sense阶段后的钩子（Parallelpattern - concurrentExecute）

        Args:
            perceptions: Perception list

        Returns:
            optional的修改后的Perception list
        """
        return perceptions

    async def before_plan(self, perception) -> Optional[Any]:
        """
        Plan阶段前的钩子（chainpattern）

        Args:
            perception: Perception input

        Returns:
            optional的修改后的Perception（ReturnNone则不ExecutePlan）
        """
        pass

    async def after_plan(self, action) -> Any:
        """
        Plan阶段后的钩子（Parallelpattern）

        Args:
            action: Action plan

        Returns:
            optional的修改后的Action
        """
        return action

    async def before_act(self, action) -> Optional[Any]:
        """
        Act阶段前的钩子（chainpattern）

        Args:
            action: Action to execute

        Returns:
            optional的修改后的action（ReturnNone则不ExecuteAct）
        """
        pass

    async def after_act(self, result) -> Any:
        """
        Act阶段后的钩子（Parallelpattern）

        Args:
            result: Execution result

        Returns:
            optional的修改后的Result
        """
        return result

    # ===== extension点 =====

    def get_tools(self) -> List:
        """
        getplugin提供的tool

        Returns:
            toollist
        """
        return []

    def get_storage_backend(self):
        """
        getplugin提供的storage后端

        Returns:
            storage后端Instance或None
        """
        return None

    def get_llm_adapter(self):
        """
        getplugin提供的LLMAdapter

        Returns:
            LLMAdapterInstance或None
        """
        return None

    def get_sensors(self) -> List:
        """
        getplugin提供的传感器

        Returns:
            传感器list
        """
        return []
