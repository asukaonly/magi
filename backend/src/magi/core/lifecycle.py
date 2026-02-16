"""
优雅启停管理器

ImplementationAgent系统的顺序启动and逆序stop，确保系统stable性
"""
import asyncio
import signal
from typing import List, Callable, Optional, Dict, Any
from enum import Enum
import time
from ..events.events import event, eventlevel


class ShutdownState(Enum):
    """关闭State"""
    runNING = "running"           # 正常run
    SHUTDOWN_REQUESTED = "shutdown_requested"  # request关闭
    SHUTDOWN_IN_PROGRESS = "shutdown_in_progress"  # 关闭中
    SHUTDOWN_COMPLETE = "shutdown_complete"      # 关闭complete


class GracefulShutdownManager:
    """
    优雅关闭管理器

    职责：
    - 管理系统启动顺序
    - 管理系统关闭顺序
    - process关闭信号（SIGTERM/SIGint）
    - timeout控制andfailureprocess
    """

    def __init__(
        self,
        shutdown_timeout: float = 30.0,
        stop_order_reversed: bool = True,
    ):
        """
        initialize优雅关闭管理器

        Args:
            shutdown_timeout: 关闭timeout时间（seconds）
            stop_order_reversed: is not逆序stop
        """
        self.shutdown_timeout = shutdown_timeout
        self.stop_order_reversed = stop_order_reversed

        # 启动阶段（按顺序）
        self._startup_stages: List[Dict[str, Any]] = []

        # 关闭State
        self._shutdown_state = ShutdownState.runNING

        # 信号process
        self._original_handlers: Dict = {}

        # 关闭callback
        self._shutdown_callbacks: List[Callable] = []

    def add_startup_stage(
        self,
        name: str,
        start_func: Callable,
        stop_func: Callable,
        dependencies: List[str] = None,
        timeout: float = 10.0,
        critical: bool = False,
    ):
        """
        add启动阶段

        Args:
            name: 阶段Name
            start_func: 启动Function
            stop_func: stopFunction
            dependencies: dependency的阶段Namelist
            timeout: timeout时间（seconds）
            critical: is not关key阶段（failure则rollback）
        """
        stage = {
            "name": name,
            "start_func": start_func,
            "stop_func": stop_func,
            "dependencies": dependencies or [],
            "timeout": timeout,
            "critical": critical,
            "started": False,
        }
        self._startup_stages.append(stage)

    async def startup(self) -> bool:
        """
        顺序启动all阶段

        Returns:
            is notall启动success
        """
        print("\n=== Starting System ===")

        # 1. 按dependencyrelationshipsort
        sorted_stages = self._sort_stages_by_dependencies()

        # 2. 顺序启动
        started_stages = []

        for stage in sorted_stages:
            print(f"Starting {stage['name']}...")

            try:
                # timeout控制
                await asyncio.wait_for(
                    stage["start_func"](),
                    timeout=stage["timeout"],
                )
                stage["started"] = True
                started_stages.append(stage)
                print(f"✓ {stage['name']} started")

            except asyncio.TimeoutError:
                print(f"✗ {stage['name']} startup timeout")
                if stage["critical"]:
                    # 关key阶段failure，rollback
                    await self._rollback_startup(started_stages)
                    return False
            except Exception as e:
                print(f"✗ {stage['name']} startup failed: {e}")
                if stage["critical"]:
                    # 关key阶段failure，rollback
                    await self._rollback_startup(started_stages)
                    return False

        # 3. Setting信号process
        self._setup_signal_handlers()

        print("=== System Started ===\n")
        return True

    async def shutdown(self) -> bool:
        """
        逆序stopall阶段

        Returns:
            is notallstopsuccess
        """
        if self._shutdown_state != ShutdownState.runNING:
            print(f"Already shutting down: {self._shutdown_state}")
            return True

        print("\n=== Shutting Down System ===")
        self._shutdown_state = ShutdownState.SHUTDOWN_REQUESTED

        # 1. notify关闭callback
        for callback in self._shutdown_callbacks:
            try:
                await callback()
            except Exception as e:
                print(f"Shutdown callback error: {e}")

        # 2. get已启动的阶段
        started_stages = [s for s in self._startup_stages if s["started"]]

        # 3. 确定stop顺序
        if self.stop_order_reversed:
            stop_stages = reversed(started_stages)
        else:
            stop_stages = started_stages

        # 4. 逆序stop
        self._shutdown_state = ShutdownState.SHUTDOWN_IN_PROGRESS

        for stage in stop_stages:
            print(f"Stopping {stage['name']}...")

            try:
                # timeout控制
                await asyncio.wait_for(
                    stage["stop_func"](),
                    timeout=stage["timeout"],
                )
                stage["started"] = False
                print(f"✓ {stage['name']} stopped")

            except asyncio.TimeoutError:
                print(f"✗ {stage['name']} stop timeout")
                # 继续stopother阶段
            except Exception as e:
                print(f"✗ {stage['name']} stop failed: {e}")
                # 继续stopother阶段

        # 5. restore信号process
        self._restore_signal_handlers()

        self._shutdown_state = ShutdownState.SHUTDOWN_COMPLETE
        print("=== System Shutdown Complete ===\n")
        return True

    async def _rollback_startup(self, started_stages: List[Dict]):
        """
        rollback已启动的阶段

        Args:
            started_stages: 已启动的阶段list
        """
        print("\n=== Rolling Back Startup ===")

        # 逆序stop已启动的阶段
        for stage in reversed(started_stages):
            print(f"Rolling back {stage['name']}...")

            try:
                await asyncio.wait_for(
                    stage["stop_func"](),
                    timeout=stage["timeout"],
                )
                stage["started"] = False
                print(f"✓ {stage['name']} rolled back")

            except Exception as e:
                print(f"✗ {stage['name']} rollback failed: {e}")

        print("=== Rollback Complete ===\n")

    def _sort_stages_by_dependencies(self) -> List[Dict]:
        """
        根据dependencyrelationship对阶段sort（拓扑sort）

        Returns:
            sort后的阶段list
        """
        # simple的拓扑sort
        sorted_stages = []
        remaining = self._startup_stages.copy()

        while remaining:
            # Found没有未满足dependency的阶段
            ready = []
            for stage in remaining:
                dependencies_met = all(
                    dep in [s["name"] for s in sorted_stages]
                    for dep in stage["dependencies"]
                )
                if dependencies_met:
                    ready.append(stage)

            if not ready:
                # 循环dependency，按原顺序add
                ready = [remaining[0]]

            for stage in ready:
                sorted_stages.append(stage)
                remaining.remove(stage)

        return sorted_stages

    def _setup_signal_handlers(self):
        """Setting信号process器"""
        # SIGTERM (killcommand)
        self._original_handlers[signal.SIGTERM] = signal.signal(
            signal.SIGTERM,
            self._signal_handler
        )

        # SIGint (Ctrl+C)
        self._original_handlers[signal.SIGint] = signal.signal(
            signal.SIGint,
            self._signal_handler
        )

    def _restore_signal_handlers(self):
        """restore原始信号process器"""
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)

    def _signal_handler(self, signum, frame):
        """信号process器"""
        print(f"\nReceived signal {signum}, initiating shutdown...")

        # 在new的event循环中Execute关闭
        asyncio.create_task(self.shutdown())

    def register_shutdown_callback(self, callback: Callable):
        """
        register关闭callback

        Args:
            callback: 关闭时调用的Function
        """
        self._shutdown_callbacks.append(callback)

    def is_shutting_down(self) -> bool:
        """
        is not正在关闭

        Returns:
            is not正在关闭
        """
        return self._shutdown_state != ShutdownState.runNING

    def get_shutdown_state(self) -> ShutdownState:
        """
        get关闭State

        Returns:
            关闭State
        """
        return self._shutdown_state


class AgentLifecycleManager:
    """
    Agent生命period管理器

    管理Master/Task/Worker三层Agent的启停
    """

    def __init__(
        self,
        master_agent,
        task_agents: List = None,
        shutdown_timeout: float = 30.0,
    ):
        """
        initializeAgent生命period管理器

        Args:
            master_agent: Master AgentInstance
            task_agents: Task Agentlist
            shutdown_timeout: 关闭timeout时间
        """
        self.master_agent = master_agent
        self.task_agents = task_agents or []
        self.shutdown_timeout = shutdown_timeout

        # create优雅关闭管理器
        self.shutdown_manager = GracefulShutdownManager(
            shutdown_timeout=shutdown_timeout,
        )

        # Setting启动阶段
        self._setup_startup_stages()

    def _setup_startup_stages(self):
        """Setting启动阶段"""
        # 阶段1: start message bus
        self.shutdown_manager.add_startup_stage(
            name="message_bus",
            start_func=self._start_message_bus,
            stop_func=self._stop_message_bus,
            critical=True,
        )

        # 阶段2: 启动Master Agent
        self.shutdown_manager.add_startup_stage(
            name="master_agent",
            start_func=self._start_master_agent,
            stop_func=self._stop_master_agent,
            dependencies=["message_bus"],
            critical=True,
        )

        # 阶段3: 启动Task Agents
        for i, task_agent in enumerate(self.task_agents):
            self.shutdown_manager.add_startup_stage(
                name=f"task_agent_{i}",
                start_func=lambda ta=task_agent: self._start_task_agent(ta),
                stop_func=lambda ta=task_agent: self._stop_task_agent(ta),
                dependencies=["master_agent"],
                critical=False,  # TaskAgentfailure不影响整体
            )

    async def _start_message_bus(self):
        """start message bus"""
        if hasattr(self.master_agent, 'message_bus'):
            await self.master_agent.message_bus.start()

    async def _stop_message_bus(self):
        """stop message bus"""
        if hasattr(self.master_agent, 'message_bus'):
            await self.master_agent.message_bus.stop()

    async def _start_master_agent(self):
        """启动Master Agent"""
        # 调用Master Agent的_on_startMethod（如果有）
        if hasattr(self.master_agent, '_on_start'):
            await self.master_agent._on_start()
        else:
            # SettingState
            from .agent import AgentState
            self.master_agent.state = AgentState.startING
            self.master_agent._start_time = time.time()

            # release启动event
            if hasattr(self.master_agent, '_publish_event'):
                await self.master_agent._publish_event(
                    "agent.started",
                    {"agent_type": "master", "name": self.master_agent.config.name}
                )

            self.master_agent.state = AgentState.runNING

    async def _stop_master_agent(self):
        """stopMaster Agent"""
        # 调用Master Agent的_on_stopMethod（如果有）
        if hasattr(self.master_agent, '_on_stop'):
            await self.master_agent._on_stop()
        else:
            # stopMain loop任务
            if hasattr(self.master_agent, '_main_loop_task'):
                task = self.master_agent._main_loop_task
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            # SettingState
            from .agent import AgentState
            self.master_agent.state = AgentState.stopPED
            self.master_agent._stop_time = time.time()

    async def _start_task_agent(self, task_agent):
        """启动Task Agent"""
        # 调用Task Agent的_on_startMethod（如果有）
        if hasattr(task_agent, '_on_start'):
            await task_agent._on_start()
        else:
            # SettingState
            from .agent import AgentState
            task_agent.state = AgentState.startING
            task_agent._start_time = time.time()
            task_agent.state = AgentState.runNING

    async def _stop_task_agent(self, task_agent):
        """stopTask Agent"""
        # 调用Task Agent的_on_stopMethod（如果有）
        if hasattr(task_agent, '_on_stop'):
            await task_agent._on_stop()
        else:
            # SettingState
            from .agent import AgentState
            task_agent.state = AgentState.stopPED
            task_agent._stop_time = time.time()

    async def startup(self) -> bool:
        """
        启动allAgent

        Returns:
            is not启动success
        """
        return await self.shutdown_manager.startup()

    async def shutdown(self) -> bool:
        """
        stopallAgent

        Returns:
            is notstopsuccess
        """
        return await self.shutdown_manager.shutdown()

    async def wait_for_shutdown(self):
        """
        等待关闭complete
        """
        while self.shutdown_manager.get_shutdown_state() != ShutdownState.SHUTDOWN_COMPLETE:
            await asyncio.sleep(0.1)

    def register_shutdown_callback(self, callback: Callable):
        """
        register关闭callback

        Args:
            callback: 关闭时调用的Function
        """
        self.shutdown_manager.register_shutdown_callback(callback)

    def is_shutting_down(self) -> bool:
        """
        is not正在关闭

        Returns:
            is not正在关闭
        """
        return self.shutdown_manager.is_shutting_down()
