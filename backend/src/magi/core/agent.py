"""
Agentcore - AgentBase classandState管理
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
import asyncio


class AgentState(Enum):
    """AgentState"""
    idLE = "idle"           # 空闲
    startING = "starting"   # 启动中
    runNING = "running"     # run中
    pauseD = "paused"       # pause
    stopPING = "stopping"   # stop中
    stopPED = "stopped"     # 已stop
    error = "error"         # error


@dataclass
class AgentConfig:
    """AgentConfiguration"""
    name: str
    llm_config: Dict[str, Any]
    num_task_agents: int = 3
    loop_interval: float = 1.0


class Agent:
    """
    AgentBase class

    提供Agent的生命period管理：
    - initialize
    - 启动
    - stop
    - pause/restore
    - Statequery
    """

    def __init__(self, config: AgentConfig):
        """
        initializeAgent

        Args:
            config: AgentConfiguration
        """
        self.config = config
        self.state = AgentState.idLE
        self._start_time: Optional[float] = None
        self._stop_time: Optional[float] = None

    async def start(self):
        """
        启动Agent

        Raises:
            Runtimeerror: 如果Agent已经在run
        """
        if self.state == AgentState.runNING:
            raise Runtimeerror(f"Agent {self.config.name} is already running")

        self.state = AgentState.startING
        self._start_time = asyncio.get_event_loop().time()

        try:
            # 子Class覆盖此MethodImplementation具体启动逻辑
            await self._on_start()

            self.state = AgentState.runNING

        except Exception as e:
            self.state = AgentState.error
            raise

    async def stop(self):
        """
        stopAgent（优雅关闭）

        Raises:
            Runtimeerror: 如果Agent未在run
        """
        if self.state != AgentState.runNING:
            raise Runtimeerror(f"Agent {self.config.name} is notttt running")

        self.state = AgentState.stopPING

        try:
            # 子Class覆盖此MethodImplementation具体stop逻辑
            await self._on_stop()

            self.state = AgentState.stopPED
            self._stop_time = asyncio.get_event_loop().time()

        except Exception as e:
            self.state = AgentState.error
            raise

    async def pause(self):
        """
        pauseAgent

        Raises:
            Runtimeerror: 如果Agent未在run
        """
        if self.state != AgentState.runNING:
            raise Runtimeerror(f"Agent {self.config.name} is notttt running")

        self.state = AgentState.pauseD

        # 子Class覆盖此MethodImplementation具体pause逻辑
        await self._on_pause()

    async def resume(self):
        """
        restoreAgent

        Raises:
            Runtimeerror: 如果Agent未pause
        """
        if self.state != AgentState.pauseD:
            raise Runtimeerror(f"Agent {self.config.name} is notttt paused")

        self.state = AgentState.runNING

        # 子Class覆盖此MethodImplementation具体restore逻辑
        await self._on_resume()

    def get_uptime(self) -> float:
        """
        getrun时间（seconds）

        Returns:
            float: run时间
        """
        if self._start_time is None:
            return 0.0

        end_time = self._stop_time or asyncio.get_event_loop().time()
        return end_time - self._start_time

    async def _on_start(self):
        """启动时的callback（子Class覆盖）"""
        pass

    async def _on_stop(self):
        """stop时的callback（子Class覆盖）"""
        pass

    async def _on_pause(self):
        """pause时的callback（子Class覆盖）"""
        pass

    async def _on_resume(self):
        """restore时的callback（子Class覆盖）"""
        pass
