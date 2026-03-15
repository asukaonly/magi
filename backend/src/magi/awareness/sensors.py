"""
Built-in sensor implementations
"""
import asyncio
from typing import Optional, Dict, Any
from .base import Perception, PerceptionType, TriggerMode


class UserMessageSensor:
    """
    User message sensor

    Listens for user message input

    Supports two modes:
    1. Queue mode: directly add messages to internal queue (for backward compatibility)
    2. MessageBus mode: subscribe to message bus USER_MESSAGE events
    """

    def __init__(self, message_queue: asyncio.Queue = None, message_bus=None):
        """
        Initialize user message sensor

        Args:
            message_queue: message queue (optional, for backward compatibility)
            message_bus: message bus instance (optional, for subscribing to events)
        """
        self._queue = message_queue or asyncio.Queue()
        self._enabled = True
        self._callback = None
        self._message_bus = message_bus
        self._subscription_id = None

    @property
    def perception_type(self) -> PerceptionType:
        """Perception type"""
        return PerceptionType.TEXT

    @property
    def trigger_mode(self) -> TriggerMode:
        """Trigger mode"""
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        """Whether enabled"""
        return self._enabled

    def enable(self):
        """Enable sensor"""
        self._enabled = True

    def disable(self):
        """Disable sensor"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        Sense once (polling mode)

        Returns:
            Perception or None
        """
        if not self._enabled:
            return None

        try:
            # non-blocking get message
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
        Listen mode (event mode)

        Args:
            callback: callback function, receives perception
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(0.1)

    async def send_message(self, message: str):
        """
        Send message to sensor (simulate user input)

        Args:
            message: message content
        """
        await self._queue.put(message)

    def get_queue(self) -> asyncio.Queue:
        """Get message queue"""
        return self._queue

    def set_message_bus(self, message_bus):
        """
        Set message bus and subscribe to USER_MESSAGE events

        Args:
            message_bus: message bus instance
        """
        self._message_bus = message_bus
        # Will auto-subscribe on startup

    async def subscribe_to_message_bus(self, event_type: str):
        """
        Subscribe to message bus event

        Args:
            event_type: event type (e.g. "UserMessage")
        """
        if self._message_bus:
            from ..events.events import EventTypes
            self._subscription_id = await self._message_bus.subscribe(
                EventTypes.USER_MESSAGE,
                self._on_message_event,
                propagation_mode="broadcast"
            )

    async def unsubscribe_from_message_bus(self):
        """Unsubscribe from message bus event"""
        if self._message_bus and self._subscription_id:
            await self._message_bus.unsubscribe(self._subscription_id)
            self._subscription_id = None

    async def _on_message_event(self, event):
        """
        message bus event callback

        Args:
            event: USER_MESSAGE event
        """
        if not self._enabled:
            return

        # Convert event data to perception message format
        message_data = dict(event.data) if isinstance(event.data, dict) else {"message": event.data}
        # Preserve message chain correlation id for unified event tracking
        if event.correlation_id:
            message_data["correlation_id"] = event.correlation_id
        await self._queue.put(message_data)


class EventSensor:
    """
    Event sensor

    Listens for system events
    """

    def __init__(self, event_bus=None):
        """
        Initialize event sensor

        Args:
            event_bus: event bus (optional)
        """
        self._event_bus = event_bus
        self._enabled = True
        self._callback = None

        # Event cache
        self._event_cache: list = []
        self._max_cache_size = 100

    @property
    def perception_type(self) -> PerceptionType:
        """Perception type"""
        return PerceptionType.EVENT

    @property
    def trigger_mode(self) -> TriggerMode:
        """Trigger mode"""
        return TriggerMode.EVENT

    @property
    def enabled(self) -> bool:
        """Whether enabled"""
        return self._enabled

    def enable(self):
        """Enable sensor"""
        self._enabled = True

    def disable(self):
        """Disable sensor"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        Sense once (polling mode)

        Returns:
            Perception or None
        """
        if not self._enabled:
            return None

        # Get event from cache
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
        Listen mode (event mode)

        Args:
            callback: callback function, receives perception
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(0.1)

    async def on_event(self, Event: Dict[str, Any]):
        """
        Event callback (called by event bus)

        Args:
            event: event data
        """
        if not self._enabled:
            return

        # Add to cache
        self._event_cache.append(event)

        # Limit cache size
        if len(self._event_cache) > self._max_cache_size:
            self._event_cache.pop(0)

    def get_cache_size(self) -> int:
        """Get cache size"""
        return len(self._event_cache)


class SensordataSensor:
    """
    Sensor data sensor

    Simulates physical sensor data input
    """

    def __init__(self, sensor_type: str = "temperature"):
        """
        Initialize sensor data sensor

        Args:
            sensor_type: sensor type
        """
        self._sensor_type = sensor_type
        self._enabled = True
        self._callback = None

        # Simulated data generator
        self._data_generator = self._create_data_generator(sensor_type)

    @property
    def perception_type(self) -> PerceptionType:
        """Perception type"""
        return PerceptionType.SENSOR

    @property
    def trigger_mode(self) -> TriggerMode:
        """Trigger mode"""
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        """Whether enabled"""
        return self._enabled

    def enable(self):
        """Enable sensor"""
        self._enabled = True

    def disable(self):
        """Disable sensor"""
        self._enabled = False

    async def sense(self) -> Optional[Perception]:
        """
        Sense once

        Returns:
            Perception or None
        """
        if not self._enabled:
            return None

        # Generate simulated data
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
        Listen mode

        Args:
            callback: callback function
        """
        self._callback = callback

        while self._enabled:
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)
            await asyncio.sleep(1.0)  # Sample once per second

    def _create_data_generator(self, sensor_type: str):
        """Create data generator"""
        async def generate_temperature():
            # Simulated temperature data (20-30°C)
            import random
            return 20 + random.random() * 10

        async def generate_humidity():
            # Simulated humidity data (40-60%)
            import random
            return 40 + random.random() * 20

        async def generate_pressure():
            # Simulated pressure data (1000-1020 hPa)
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
    Timer sensor

    Triggers perception events on a schedule
    """

    def __init__(self, interval: float = 60.0):
        """
        Initialize timer sensor

        Args:
            interval: trigger interval (seconds)
        """
        self._interval = interval
        self._enabled = True
        self._callback = None
        self._task = None

    @property
    def perception_type(self) -> PerceptionType:
        """Perception type"""
        return PerceptionType.EVENT

    @property
    def trigger_mode(self) -> TriggerMode:
        """Trigger mode"""
        return TriggerMode.HYBRID

    @property
    def enabled(self) -> bool:
        """Whether enabled"""
        return self._enabled

    def enable(self):
        """Enable sensor"""
        self._enabled = True

    def disable(self):
        """Disable sensor"""
        self._enabled = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def sense(self) -> Optional[Perception]:
        """
        Sense once (immediate trigger)

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
        Listen mode (scheduled trigger)

        Args:
            callback: callback function
        """
        self._callback = callback

        while self._enabled:
            # Wait for specified interval
            await asyncio.sleep(self._interval)

            # Trigger perception
            perception = await self.sense()
            if perception and self._callback:
                await self._callback(perception)

    def set_interval(self, interval: float):
        """
        Set trigger interval

        Args:
            interval: interval (seconds)
        """
        self._interval = interval
