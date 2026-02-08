"""
系统监控模块
"""
import asyncio
from typing import Dict, Any
from dataclasses import dataclass
import time


@dataclass
class SystemMetrics:
    """系统指标"""
    cpu_percent: float           # CPU使用率
    memory_percent: float        # 内存使用率
    memory_used: int             # 已用内存（字节）
    memory_total: int            # 总内存（字节）
    disk_used: int               # 已用磁盘（字节）
    disk_total: int              # 总磁盘（字节）
    agent_count: int             # Agent数量
    task_count: int              # 任务数量
    timestamp: float             # 时间戳


class SystemMonitor:
    """
    系统监控器

    监控CPU、内存等系统资源使用情况
    """

    def __init__(self, update_interval: float = 5.0):
        """
        初始化系统监控器

        Args:
            update_interval: 更新间隔（秒）
        """
        self.update_interval = update_interval
        self._running = False
        self._task = None

        # 当前指标
        self._current_metrics: SystemMetrics = None

        # 历史指标（最近100个）
        self._history: list = []
        self._max_history = 100

    async def start(self):
        """启动监控"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

        # 立即更新一次
        await self.update()

    async def stop(self):
        """停止监控"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def update(self):
        """更新系统指标"""
        try:
            import psutil

            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=0.1)

            # 内存信息
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used = memory.used
            memory_total = memory.total

            # 磁盘信息
            disk = psutil.disk_usage('/')
            disk_used = disk.used
            disk_total = disk.total

            # 创建指标对象
            self._current_metrics = SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used=memory_used,
                memory_total=memory_total,
                disk_used=disk_used,
                disk_total=disk_total,
                agent_count=0,  # 由外部设置
                task_count=0,  # 由外部设置
                timestamp=time.time(),
            )

            # 添加到历史
            self._history.append(self._current_metrics)
            if len(self._history) > self._max_history:
                self._history.pop(0)

        except ImportError:
            # psutil未安装，返回默认值
            self._current_metrics = SystemMetrics(
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_used=0,
                memory_total=0,
                disk_used=0,
                disk_total=0,
                agent_count=0,
                task_count=0,
                timestamp=time.time(),
            )

    def get_current_metrics(self) -> SystemMetrics:
        """
        获取当前指标

        Returns:
            当前系统指标
        """
        return self._current_metrics

    def get_history(self, limit: int = 100) -> list:
        """
        获取历史指标

        Args:
            limit: 最大数量

        Returns:
            历史指标列表
        """
        return self._history[-limit:]

    def is_overloaded(self, thresholds: Dict[str, float] = None) -> bool:
        """
        判断系统是否过载

        Args:
            thresholds: 阈值配置

        Returns:
            是否过载
        """
        if not self._current_metrics:
            return False

        # 默认阈值
        default_thresholds = {
            "cpu_percent": 80.0,
            "memory_percent": 80.0,
        }

        if thresholds:
            default_thresholds.update(thresholds)

        # 检查CPU
        if self._current_metrics.cpu_percent > default_thresholds["cpu_percent"]:
            return True

        # 检查内存
        if self._current_metrics.memory_percent > default_thresholds["memory_percent"]:
            return True

        return False

    def set_agent_count(self, count: int):
        """设置Agent数量"""
        if self._current_metrics:
            self._current_metrics.agent_count = count

    def set_task_count(self, count: int):
        """设置任务数量"""
        if self._current_metrics:
            self._current_metrics.task_count = count

    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                await self.update()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in monitor loop: {e}")
                await asyncio.sleep(self.update_interval)


class AgentMetrics:
    """
    Agent指标收集器

    收集单个Agent的运行指标
    """

    def __init__(self, agent_id: str):
        """
        初始化Agent指标收集器

        Args:
            agent_id: Agent ID
        """
        self.agent_id = agent_id

        # 基本指标
        self.start_time: float = None
        self.loop_count: int = 0
        self.success_count: int = 0
        self.error_count: int = 0

        # 性能指标
        self.loop_durations: list = []  # 循环耗时
        self.max_loop_duration: float = 0.0
        self.avg_loop_duration: float = 0.0

        # 任务指标
        self.tasks_completed: int = 0
        self.tasks_failed: int = 0

    def start(self):
        """启动指标收集"""
        self.start_time = time.time()

    def record_loop(self, duration: float):
        """
        记录一次循环

        Args:
            duration: 耗时（秒）
        """
        self.loop_count += 1

        # 记录耗时
        self.loop_durations.append(duration)

        # 更新最大耗时
        if duration > self.max_loop_duration:
            self.max_loop_duration = duration

        # 更新平均耗时
        self.avg_loop_duration = sum(self.loop_durations) / len(self.loop_durations)

        # 限制历史长度
        if len(self.loop_durations) > 100:
            self.loop_durations.pop(0)

    def record_success(self):
        """记录成功"""
        self.success_count += 1

    def record_error(self):
        """记录错误"""
        self.error_count += 1

    def record_task_completed(self):
        """记录任务完成"""
        self.tasks_completed += 1

    def record_task_failed(self):
        """记录任务失败"""
        self.tasks_failed += 1

    def get_metrics(self) -> Dict[str, Any]:
        """
        获取指标

        Returns:
            指标字典
        """
        uptime = 0.0
        if self.start_time:
            uptime = time.time() - self.start_time

        return {
            "agent_id": self.agent_id,
            "uptime": uptime,
            "loop_count": self.loop_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "max_loop_duration": self.max_loop_duration,
            "avg_loop_duration": self.avg_loop_duration,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "success_rate": (
                self.success_count / self.loop_count
                if self.loop_count > 0
                else 0
            ),
        }
