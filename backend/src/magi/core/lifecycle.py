"""
优雅启停管理器

实现Agent系统的顺序启动和逆序停止，确保系统稳定性
"""
import asyncio
import signal
from typing import List, Callable, Optional, Dict, Any
from enum import Enum
import time
from ..events.events import Event, EventLevel


class ShutdownState(Enum):
    """关闭状态"""
    RUNNING = "running"           # 正常运行
    SHUTDOWN_REQUESTED = "shutdown_requested"  # 请求关闭
    SHUTDOWN_IN_PROGRESS = "shutdown_in_progress"  # 关闭中
    SHUTDOWN_COMPLETE = "shutdown_complete"      # 关闭完成


class GracefulShutdownManager:
    """
    优雅关闭管理器

    职责：
    - 管理系统启动顺序
    - 管理系统关闭顺序
    - 处理关闭信号（SIGTERM/SIGINT）
    - 超时控制和失败处理
    """

    def __init__(
        self,
        shutdown_timeout: float = 30.0,
        stop_order_reversed: bool = True,
    ):
        """
        初始化优雅关闭管理器

        Args:
            shutdown_timeout: 关闭超时时间（秒）
            stop_order_reversed: 是否逆序停止
        """
        self.shutdown_timeout = shutdown_timeout
        self.stop_order_reversed = stop_order_reversed

        # 启动阶段（按顺序）
        self._startup_stages: List[Dict[str, Any]] = []

        # 关闭状态
        self._shutdown_state = ShutdownState.RUNNING

        # 信号处理
        self._original_handlers: Dict = {}

        # 关闭回调
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
        添加启动阶段

        Args:
            name: 阶段名称
            start_func: 启动函数
            stop_func: 停止函数
            dependencies: 依赖的阶段名称列表
            timeout: 超时时间（秒）
            critical: 是否关键阶段（失败则回滚）
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
        顺序启动所有阶段

        Returns:
            是否全部启动成功
        """
        print("\n=== Starting System ===")

        # 1. 按依赖关系排序
        sorted_stages = self._sort_stages_by_dependencies()

        # 2. 顺序启动
        started_stages = []

        for stage in sorted_stages:
            print(f"Starting {stage['name']}...")

            try:
                # 超时控制
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
                    # 关键阶段失败，回滚
                    await self._rollback_startup(started_stages)
                    return False
            except Exception as e:
                print(f"✗ {stage['name']} startup failed: {e}")
                if stage["critical"]:
                    # 关键阶段失败，回滚
                    await self._rollback_startup(started_stages)
                    return False

        # 3. 设置信号处理
        self._setup_signal_handlers()

        print("=== System Started ===\n")
        return True

    async def shutdown(self) -> bool:
        """
        逆序停止所有阶段

        Returns:
            是否全部停止成功
        """
        if self._shutdown_state != ShutdownState.RUNNING:
            print(f"Already shutting down: {self._shutdown_state}")
            return True

        print("\n=== Shutting Down System ===")
        self._shutdown_state = ShutdownState.SHUTDOWN_REQUESTED

        # 1. 通知关闭回调
        for callback in self._shutdown_callbacks:
            try:
                await callback()
            except Exception as e:
                print(f"Shutdown callback error: {e}")

        # 2. 获取已启动的阶段
        started_stages = [s for s in self._startup_stages if s["started"]]

        # 3. 确定停止顺序
        if self.stop_order_reversed:
            stop_stages = reversed(started_stages)
        else:
            stop_stages = started_stages

        # 4. 逆序停止
        self._shutdown_state = ShutdownState.SHUTDOWN_IN_PROGRESS

        for stage in stop_stages:
            print(f"Stopping {stage['name']}...")

            try:
                # 超时控制
                await asyncio.wait_for(
                    stage["stop_func"](),
                    timeout=stage["timeout"],
                )
                stage["started"] = False
                print(f"✓ {stage['name']} stopped")

            except asyncio.TimeoutError:
                print(f"✗ {stage['name']} stop timeout")
                # 继续停止其他阶段
            except Exception as e:
                print(f"✗ {stage['name']} stop failed: {e}")
                # 继续停止其他阶段

        # 5. 恢复信号处理
        self._restore_signal_handlers()

        self._shutdown_state = ShutdownState.SHUTDOWN_COMPLETE
        print("=== System Shutdown Complete ===\n")
        return True

    async def _rollback_startup(self, started_stages: List[Dict]):
        """
        回滚已启动的阶段

        Args:
            started_stages: 已启动的阶段列表
        """
        print("\n=== Rolling Back Startup ===")

        # 逆序停止已启动的阶段
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
        根据依赖关系对阶段排序（拓扑排序）

        Returns:
            排序后的阶段列表
        """
        # 简单的拓扑排序
        sorted_stages = []
        remaining = self._startup_stages.copy()

        while remaining:
            # 找到没有未满足依赖的阶段
            ready = []
            for stage in remaining:
                dependencies_met = all(
                    dep in [s["name"] for s in sorted_stages]
                    for dep in stage["dependencies"]
                )
                if dependencies_met:
                    ready.append(stage)

            if not ready:
                # 循环依赖，按原顺序添加
                ready = [remaining[0]]

            for stage in ready:
                sorted_stages.append(stage)
                remaining.remove(stage)

        return sorted_stages

    def _setup_signal_handlers(self):
        """设置信号处理器"""
        # SIGTERM (kill命令)
        self._original_handlers[signal.SIGTERM] = signal.signal(
            signal.SIGTERM,
            self._signal_handler
        )

        # SIGINT (Ctrl+C)
        self._original_handlers[signal.SIGINT] = signal.signal(
            signal.SIGINT,
            self._signal_handler
        )

    def _restore_signal_handlers(self):
        """恢复原始信号处理器"""
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)

    def _signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\nReceived signal {signum}, initiating shutdown...")

        # 在新的事件循环中执行关闭
        asyncio.create_task(self.shutdown())

    def register_shutdown_callback(self, callback: Callable):
        """
        注册关闭回调

        Args:
            callback: 关闭时调用的函数
        """
        self._shutdown_callbacks.append(callback)

    def is_shutting_down(self) -> bool:
        """
        是否正在关闭

        Returns:
            是否正在关闭
        """
        return self._shutdown_state != ShutdownState.RUNNING

    def get_shutdown_state(self) -> ShutdownState:
        """
        获取关闭状态

        Returns:
            关闭状态
        """
        return self._shutdown_state


class AgentLifecycleManager:
    """
    Agent生命周期管理器

    管理Master/Task/Worker三层Agent的启停
    """

    def __init__(
        self,
        master_agent,
        task_agents: List = None,
        shutdown_timeout: float = 30.0,
    ):
        """
        初始化Agent生命周期管理器

        Args:
            master_agent: Master Agent实例
            task_agents: Task Agent列表
            shutdown_timeout: 关闭超时时间
        """
        self.master_agent = master_agent
        self.task_agents = task_agents or []
        self.shutdown_timeout = shutdown_timeout

        # 创建优雅关闭管理器
        self.shutdown_manager = GracefulShutdownManager(
            shutdown_timeout=shutdown_timeout,
        )

        # 设置启动阶段
        self._setup_startup_stages()

    def _setup_startup_stages(self):
        """设置启动阶段"""
        # 阶段1: 启动消息总线
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
                critical=False,  # TaskAgent失败不影响整体
            )

    async def _start_message_bus(self):
        """启动消息总线"""
        if hasattr(self.master_agent, 'message_bus'):
            await self.master_agent.message_bus.start()

    async def _stop_message_bus(self):
        """停止消息总线"""
        if hasattr(self.master_agent, 'message_bus'):
            await self.master_agent.message_bus.stop()

    async def _start_master_agent(self):
        """启动Master Agent"""
        # 调用Master Agent的_on_start方法（如果有）
        if hasattr(self.master_agent, '_on_start'):
            await self.master_agent._on_start()
        else:
            # 设置状态
            from .agent import AgentState
            self.master_agent.state = AgentState.STARTING
            self.master_agent._start_time = time.time()

            # 发布启动事件
            if hasattr(self.master_agent, '_publish_event'):
                await self.master_agent._publish_event(
                    "agent.started",
                    {"agent_type": "master", "name": self.master_agent.config.name}
                )

            self.master_agent.state = AgentState.RUNNING

    async def _stop_master_agent(self):
        """停止Master Agent"""
        # 调用Master Agent的_on_stop方法（如果有）
        if hasattr(self.master_agent, '_on_stop'):
            await self.master_agent._on_stop()
        else:
            # 停止主循环任务
            if hasattr(self.master_agent, '_main_loop_task'):
                task = self.master_agent._main_loop_task
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            # 设置状态
            from .agent import AgentState
            self.master_agent.state = AgentState.STOPPED
            self.master_agent._stop_time = time.time()

    async def _start_task_agent(self, task_agent):
        """启动Task Agent"""
        # 调用Task Agent的_on_start方法（如果有）
        if hasattr(task_agent, '_on_start'):
            await task_agent._on_start()
        else:
            # 设置状态
            from .agent import AgentState
            task_agent.state = AgentState.STARTING
            task_agent._start_time = time.time()
            task_agent.state = AgentState.RUNNING

    async def _stop_task_agent(self, task_agent):
        """停止Task Agent"""
        # 调用Task Agent的_on_stop方法（如果有）
        if hasattr(task_agent, '_on_stop'):
            await task_agent._on_stop()
        else:
            # 设置状态
            from .agent import AgentState
            task_agent.state = AgentState.STOPPED
            task_agent._stop_time = time.time()

    async def startup(self) -> bool:
        """
        启动所有Agent

        Returns:
            是否启动成功
        """
        return await self.shutdown_manager.startup()

    async def shutdown(self) -> bool:
        """
        停止所有Agent

        Returns:
            是否停止成功
        """
        return await self.shutdown_manager.shutdown()

    async def wait_for_shutdown(self):
        """
        等待关闭完成
        """
        while self.shutdown_manager.get_shutdown_state() != ShutdownState.SHUTDOWN_COMPLETE:
            await asyncio.sleep(0.1)

    def register_shutdown_callback(self, callback: Callable):
        """
        注册关闭回调

        Args:
            callback: 关闭时调用的函数
        """
        self.shutdown_manager.register_shutdown_callback(callback)

    def is_shutting_down(self) -> bool:
        """
        是否正在关闭

        Returns:
            是否正在关闭
        """
        return self.shutdown_manager.is_shutting_down()
