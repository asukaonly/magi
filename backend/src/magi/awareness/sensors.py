"""
内置传感器实现
"""
import asyncio
from typing import Optional, Dict, Any
from .base import Perception, PerceptionType, TriggerMode


class UserMessageSensor:
    """
    用户消息传感器

    监听用户消息输入
    """

    def __init__(self, message_queue: asyncio.Queue = None):
        """
        初始化用户消息传感器

        Args:
            message_queue: 消息队列（可选）
        """
        self._queue = message_queue or asyncio.Queue()
        self._enabled = True
        self._callback = None

    @property
    def perception_type(self) -> PerceptionType:
        """感知类型"""
        return PerceptionType.TEXT

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发模式"""
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    def enable(self):
        """启用传感器"""
        self._enabled = True

    def disable(self):
        """禁用传感器"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        感知一次（轮询模式）

        Returns:
            感知或None
        """
        if not self._enabled:
            return None

        try:
            # 非阻塞获取消息
            message = await asyncio.wait_for(
                self._queue.get(),
                timeout=0.1
            )
            import time
            return Perception(
                type=self.perception_type.value,
                data={"message": message},
                source="user_message_sensor",
                timestamp=time.time(),
            )
        except asyncio.TimeoutError:
            return None

    async def listen(self, callback):
        """
        监听模式（事件模式）

        Args:
            callback: 回调函数，接收Perception
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(0.1)

    async def send_message(self, message: str):
        """
        发送消息到传感器（模拟用户输入）

        Args:
            message: 消息内容
        """
        await self._queue.put(message)

    def get_queue(self) -> asyncio.Queue:
        """获取消息队列"""
        return self._queue


class EventSensor:
    """
    事件传感器

    监听系统事件
    """

    def __init__(self, event_bus=None):
        """
        初始化事件传感器

        Args:
            event_bus: 事件总线（可选）
        """
        self._event_bus = event_bus
        self._enabled = True
        self._callback = None

        # 事件缓存
        self._event_cache: list = []
        self._max_cache_size = 100

    @property
    def perception_type(self) -> PerceptionType:
        """感知类型"""
        return PerceptionType.EVENT

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发模式"""
        return TriggerMode.EVENT

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    def enable(self):
        """启用传感器"""
        self._enabled = True

    def disable(self):
        """禁用传感器"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        感知一次（轮询模式）

        Returns:
            感知或None
        """
        if not self._enabled:
            return None

        # 从缓存获取事件
        if self._event_cache:
            event = self._event_cache.pop(0)
            import time
            return Perception(
                type=self.perception_type.value,
                data=event,
                source="event_sensor",
                timestamp=time.time(),
            )

        return None

    async def listen(self, callback):
        """
        监听模式（事件模式）

        Args:
            callback: 回调函数，接收Perception
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(0.1)

    async def on_event(self, event: Dict[str, Any]):
        """
        事件回调（由事件总线调用）

        Args:
            event: 事件数据
        """
        if not self._enabled:
            return

        # 添加到缓存
        self._event_cache.append(event)

        # 限制缓存大小
        if len(self._event_cache) > self._max_cache_size:
            self._event_cache.pop(0)

    def get_cache_size(self) -> int:
        """获取缓存大小"""
        return len(self._event_cache)


class SensorDataSensor:
    """
    传感器数据传感器

    模拟物理传感器数据输入
    """

    def __init__(self, sensor_type: str = "temperature"):
        """
        初始化传感器数据传感器

        Args:
            sensor_type: 传感器类型
        """
        self._sensor_type = sensor_type
        self._enabled = True
        self._callback = None

        # 模拟数据生成
        self._data_generator = self._create_data_generator(sensor_type)

    @property
    def perception_type(self) -> PerceptionType:
        """感知类型"""
        return PerceptionType.SENSOR

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发模式"""
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    def enable(self):
        """启用传感器"""
        self._enabled = True

    def disable(self):
        """禁用传感器"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        感知一次

        Returns:
            感知或None
        """
        if not self._enabled:
            return None

        # 生成模拟数据
        data = await self._data_generator()

        import time
        return Perception(
            type=self.perception_type.value,
            data={
                "sensor_type": self._sensor_type,
                "value": data,
            },
            source="sensor_data_sensor",
            timestamp=time.time(),
        )

    async def listen(self, callback):
        """
        监听模式

        Args:
            callback: 回调函数
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(1.0)  # 每秒采样一次

    def _create_data_generator(self, sensor_type: str):
        """创建数据生成器"""
        async def generate_temperature():
            # 模拟温度数据 (20-30度)
            import random
            return 20 + random.random() * 10

        async def generate_humidity():
            # 模拟湿度数据 (40-60%)
            import random
            return 40 + random.random() * 20

        async def generate_pressure():
            # 模拟气压数据 (1000-1020 hPa)
            import random
            return 1000 + random.random() * 20

        generators = {
            "temperature": generate_temperature,
            "humidity": generate_humidity,
            "pressure": generate_pressure,
        }

        return generators.get(sensor_type, generate_temperature)


class TimerSensor:
    """
    定时传感器

    定时触发感知事件
    """

    def __init__(self, interval: float = 60.0):
        """
        初始化定时传感器

        Args:
            interval: 触发间隔（秒）
        """
        self._interval = interval
        self._enabled = True
        self._callback = None
        self._task = None

    @property
    def perception_type(self) -> PerceptionType:
        """感知类型"""
        return PerceptionType.EVENT

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发模式"""
        return TriggerMode.HYBRID

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    def enable(self):
        """启用传感器"""
        self._enabled = True

    def disable(self):
        """禁用传感器"""
        self._enabled = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def sense(self) -> Optional[Perception]:
        """
        感知一次（立即触发）

        Returns:
            感知
        """
        import time

        return Perception(
            type=self.perception_type.value,
            data={
                "event_type": "timer",
                "interval": self._interval,
            },
            source="timer_sensor",
            timestamp=time.time(),
        )

    async def listen(self, callback):
        """
        监听模式（定时触发）

        Args:
            callback: 回调函数
        """
        self._callback = callback

        while self._enabled:
            # 等待指定间隔
            await asyncio.sleep(self._interval)

            # 触发感知
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)

    def set_interval(self, interval: float):
        """
        设置触发间隔

        Args:
            interval: 间隔（秒）
        """
        self._interval = interval
