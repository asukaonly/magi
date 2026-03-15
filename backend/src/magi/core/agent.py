"""
Agent core - Agent base class and state management
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
import asyncio


class AgentState(Enum):
    """Agent state"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentConfig:
    """Agent configuration"""
    name: str
    llm_config: Dict[str, Any]
    num_task_agents: int = 3
    loop_interval: float = 1.0


class Agent:
    """
    Agent base class

    Provides Agent lifecycle management:
    - Initialize
    - Start
    - Stop
    - Pause/Resume
    - State query
    """

    def __init__(self, config: AgentConfig):
        """
        Initialize Agent

        Args:
            config: Agent configuration
        """
        self.config = config
        self.state = AgentState.IDLE
        self._start_time: Optional[float] = None
        self._stop_time: Optional[float] = None

    async def start(self):
        """
        Start Agent

        Raises:
            RuntimeError: If Agent is already running
        """
        if self.state == AgentState.RUNNING:
            raise RuntimeError(f"Agent {self.config.name} is already running")

        self.state = AgentState.STARTING
        self._start_time = asyncio.get_event_loop().time()

        try:
            # Subclass overrides this method to implement specific start logic
            await self._on_start()

            self.state = AgentState.RUNNING

        except Exception as e:
            self.state = AgentState.ERROR
            raise

    async def stop(self):
        """
        Stop Agent (graceful shutdown)

        Raises:
            RuntimeError: If Agent is not running
        """
        if self.state != AgentState.RUNNING:
            raise RuntimeError(f"Agent {self.config.name} is not running")

        self.state = AgentState.STOPPING

        try:
            # Subclass overrides this method to implement specific stop logic
            await self._on_stop()

            self.state = AgentState.STOPPED
            self._stop_time = asyncio.get_event_loop().time()

        except Exception as e:
            self.state = AgentState.ERROR
            raise

    async def pause(self):
        """
        Pause Agent

        Raises:
            RuntimeError: If Agent is not running
        """
        if self.state != AgentState.RUNNING:
            raise RuntimeError(f"Agent {self.config.name} is not running")

        self.state = AgentState.PAUSED

        # Subclass overrides this method to implement specific pause logic
        await self._on_pause()

    async def resume(self):
        """
        Resume Agent

        Raises:
            RuntimeError: If Agent is not paused
        """
        if self.state != AgentState.PAUSED:
            raise RuntimeError(f"Agent {self.config.name} is not paused")

        self.state = AgentState.RUNNING

        # Subclass overrides this method to implement specific resume logic
        await self._on_resume()

    def get_uptime(self) -> float:
        """
        Get uptime in seconds

        Returns:
            float: Uptime in seconds
        """
        if self._start_time is None:
            return 0.0

        end_time = self._stop_time or asyncio.get_event_loop().time()
        return end_time - self._start_time

    async def _on_start(self):
        """Callback on start (subclass override)"""
        pass

    async def _on_stop(self):
        """Callback on stop (subclass override)"""
        pass

    async def _on_pause(self):
        """Callback on pause (subclass override)"""
        pass

    async def _on_resume(self):
        """Callback on resume (subclass override)"""
        pass
