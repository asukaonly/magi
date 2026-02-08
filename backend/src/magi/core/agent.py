"""
Agent核心 - Agent基类和状态管理
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
import asyncio


class AgentState(Enum):
    """Agent状态"""
    IDLE = "idle"           # 空闲
    STARTING = "starting"   # 启动中
    RUNNING = "running"     # 运行中
    PAUSED = "paused"       # 暂停
    STOPPING = "stopping"   # 停止中
    STOPPED = "stopped"     # 已停止
    ERROR = "error"         # 错误


@dataclass
class AgentConfig:
    """Agent配置"""
    name: str
    llm_config: Dict[str, Any]
    num_task_agents: int = 3
    loop_interval: float = 1.0


class Agent:
    """
    Agent基类

    提供Agent的生命周期管理：
    - 初始化
    - 启动
    - 停止
    - 暂停/恢复
    - 状态查询
    """

    def __init__(self, config: AgentConfig):
        """
        初始化Agent

        Args:
            config: Agent配置
        """
        self.config = config
        self.state = AgentState.IDLE
        self._start_time: Optional[float] = None
        self._stop_time: Optional[float] = None

    async def start(self):
        """
        启动Agent

        Raises:
            RuntimeError: 如果Agent已经在运行
        """
        if self.state == AgentState.RUNNING:
            raise RuntimeError(f"Agent {self.config.name} is already running")

        self.state = AgentState.STARTING
        self._start_time = asyncio.get_event_loop().time()

        try:
            # 子类覆盖此方法实现具体启动逻辑
            await self._on_start()

            self.state = AgentState.RUNNING

        except Exception as e:
            self.state = AgentState.ERROR
            raise

    async def stop(self):
        """
        停止Agent（优雅关闭）

        Raises:
            RuntimeError: 如果Agent未在运行
        """
        if self.state != AgentState.RUNNING:
            raise RuntimeError(f"Agent {self.config.name} is not running")

        self.state = AgentState.STOPPING

        try:
            # 子类覆盖此方法实现具体停止逻辑
            await self._on_stop()

            self.state = AgentState.STOPPED
            self._stop_time = asyncio.get_event_loop().time()

        except Exception as e:
            self.state = AgentState.ERROR
            raise

    async def pause(self):
        """
        暂停Agent

        Raises:
            RuntimeError: 如果Agent未在运行
        """
        if self.state != AgentState.RUNNING:
            raise RuntimeError(f"Agent {self.config.name} is not running")

        self.state = AgentState.PAUSED

        # 子类覆盖此方法实现具体暂停逻辑
        await self._on_pause()

    async def resume(self):
        """
        恢复Agent

        Raises:
            RuntimeError: 如果Agent未暂停
        """
        if self.state != AgentState.PAUSED:
            raise RuntimeError(f"Agent {self.config.name} is not paused")

        self.state = AgentState.RUNNING

        # 子类覆盖此方法实现具体恢复逻辑
        await self._on_resume()

    def get_uptime(self) -> float:
        """
        获取运行时间（秒）

        Returns:
            float: 运行时间
        """
        if self._start_time is None:
            return 0.0

        end_time = self._stop_time or asyncio.get_event_loop().time()
        return end_time - self._start_time

    async def _on_start(self):
        """启动时的回调（子类覆盖）"""
        pass

    async def _on_stop(self):
        """停止时的回调（子类覆盖）"""
        pass

    async def _on_pause(self):
        """暂停时的回调（子类覆盖）"""
        pass

    async def _on_resume(self):
        """恢复时的回调（子类覆盖）"""
        pass
