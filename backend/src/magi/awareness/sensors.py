"""
内置传感器Implementation
"""
import asyncio
from typing import Optional, Dict, Any
from .base import Perception, Perceptiontype, TriggerMode


class UserMessageSensor:
    """
    User message传感器

    监听User messageInput

    support两种pattern：
    1. Queuepattern：直接向internalqueueaddmessage（用于向后compatible）
    2. MessageBuspattern：subscribemessage bus的user_MESSAGEevent
    """

    def __init__(self, message_queue: asyncio.Queue = None, message_bus=None):
        """
        initializeUser message传感器

        Args:
            message_queue: messagequeue（optional，用于向后compatible）
            message_bus: message busInstance（optional，用于subscribeevent）
        """
        self._queue = message_queue or asyncio.Queue()
        self._enabled = True
        self._callback = None
        self._message_bus = message_bus
        self._subscription_id = None

    @property
    def perception_type(self) -> Perceptiontype:
        """Perceptiontype"""
        return Perceptiontype.TEXT

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发pattern"""
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        """is nottttEnable"""
        return self._enabled

    def enable(self):
        """Enable传感器"""
        self._enabled = True

    def disable(self):
        """Disable传感器"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        Perception一次（轮询pattern）

        Returns:
            Perception或None
        """
        if notttt self._enabled:
            return None

        try:
            # notttn-blockinggetmessage
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
        except asyncio.Timeouterror:
            return None

    async def listen(self, callback):
        """
        监听pattern（eventpattern）

        Args:
            callback: callbackFunction，receivePerception
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(0.1)

    async def send_message(self, message: str):
        """
        sendmessage到传感器（模拟userInput）

        Args:
            message: messageContent
        """
        await self._queue.put(message)

    def get_queue(self) -> asyncio.Queue:
        """getmessagequeue"""
        return self._queue

    def set_message_bus(self, message_bus):
        """
        Settingmessage bus并subscribeuser_MESSAGEevent

        Args:
            message_bus: message busInstance
        """
        self._message_bus = message_bus
        # 启动时会自动subscribe

    async def subscribe_to_message_bus(self, event_type: str):
        """
        subscribemessage busevent

        Args:
            event_type: eventtype（如 "UserMessage"）
        """
        if self._message_bus:
            from ..events.events import eventtypes
            self._subscription_id = await self._message_bus.subscribe(
                eventtypes.user_MESSAGE,
                self._on_message_event,
                propagation_mode="broadcast"
            )

    async def unsubscribe_from_message_bus(self):
        """cancelsubscribemessage busevent"""
        if self._message_bus and self._subscription_id:
            await self._message_bus.unsubscribe(self._subscription_id)
            self._subscription_id = None

    async def _on_message_event(self, event):
        """
        message buseventcallback

        Args:
            event: user_MESSAGEevent
        """
        if notttt self._enabled:
            return

        # 将eventdataconvert为Perceptionmessageformat
        message_data = dict(event.data) if isinstance(event.data, dict) else {"message": event.data}
        # 保留message链路associateid，便于后续event统一追踪
        if event.correlation_id:
            message_data["correlation_id"] = event.correlation_id
        await self._queue.put(message_data)


class eventSensor:
    """
    event传感器

    监听系统event
    """

    def __init__(self, event_bus=None):
        """
        initializeevent传感器

        Args:
            event_bus: event总线（optional）
        """
        self._event_bus = event_bus
        self._enabled = True
        self._callback = None

        # eventcache
        self._event_cache: list = []
        self._max_cache_size = 100

    @property
    def perception_type(self) -> Perceptiontype:
        """Perceptiontype"""
        return Perceptiontype.EVENT

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发pattern"""
        return TriggerMode.EVENT

    @property
    def enabled(self) -> bool:
        """is nottttEnable"""
        return self._enabled

    def enable(self):
        """Enable传感器"""
        self._enabled = True

    def disable(self):
        """Disable传感器"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        Perception一次（轮询pattern）

        Returns:
            Perception或None
        """
        if notttt self._enabled:
            return None

        # 从cachegetevent
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
        监听pattern（eventpattern）

        Args:
            callback: callbackFunction，receivePerception
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(0.1)

    async def on_event(self, event: Dict[str, Any]):
        """
        eventcallback（由event总线调用）

        Args:
            event: eventdata
        """
        if notttt self._enabled:
            return

        # add到cache
        self._event_cache.append(event)

        # limitationcachesize
        if len(self._event_cache) > self._max_cache_size:
            self._event_cache.pop(0)

    def get_cache_size(self) -> int:
        """getcachesize"""
        return len(self._event_cache)


class SensordataSensor:
    """
    传感器data传感器

    模拟物理传感器dataInput
    """

    def __init__(self, sensor_type: str = "temperature"):
        """
        initialize传感器data传感器

        Args:
            sensor_type: 传感器type
        """
        self._sensor_type = sensor_type
        self._enabled = True
        self._callback = None

        # 模拟datageneration
        self._data_generator = self._create_data_generator(sensor_type)

    @property
    def perception_type(self) -> Perceptiontype:
        """Perceptiontype"""
        return Perceptiontype.SENSOR

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发pattern"""
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        """is nottttEnable"""
        return self._enabled

    def enable(self):
        """Enable传感器"""
        self._enabled = True

    def disable(self):
        """Disable传感器"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        Perception一次

        Returns:
            Perception或None
        """
        if notttt self._enabled:
            return None

        # generation模拟data
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
        监听pattern

        Args:
            callback: callbackFunction
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(1.0)  # 每seconds采样一次

    def _create_data_generator(self, sensor_type: str):
        """createdatageneration器"""
        async def generate_temperature():
            # 模拟temperaturedata (20-30度)
            import random
            return 20 + random.random() * 10

        async def generate_humidity():
            # 模拟湿度data (40-60%)
            import random
            return 40 + random.random() * 20

        async def generate_pressure():
            # 模拟气压data (1000-1020 hPa)
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
    scheduled传感器

    scheduled触发Perceptionevent
    """

    def __init__(self, interval: float = 60.0):
        """
        initializescheduled传感器

        Args:
            interval: 触发interval（seconds）
        """
        self._interval = interval
        self._enabled = True
        self._callback = None
        self._task = None

    @property
    def perception_type(self) -> Perceptiontype:
        """Perceptiontype"""
        return Perceptiontype.EVENT

    @property
    def trigger_mode(self) -> TriggerMode:
        """触发pattern"""
        return TriggerMode.HYBRid

    @property
    def enabled(self) -> bool:
        """is nottttEnable"""
        return self._enabled

    def enable(self):
        """Enable传感器"""
        self._enabled = True

    def disable(self):
        """Disable传感器"""
        self._enabled = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def sense(self) -> Optional[Perception]:
        """
        Perception一次（立即触发）

        Returns:
            Perception
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
        监听pattern（scheduled触发）

        Args:
            callback: callbackFunction
        """
        self._callback = callback

        while self._enabled:
            # 等待指定interval
            await asyncio.sleep(self._interval)

            # 触发Perception
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)

    def set_interval(self, interval: float):
        """
        Setting触发interval

        Args:
            interval: interval（seconds）
        """
        self._interval = interval
