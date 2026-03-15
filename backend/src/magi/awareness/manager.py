"""
Perception module - perception manager (full version)
"""
import asyncio
import bisect
from typing import List, Optional, Callable, Dict, Any
from collections import deque
from .base import Perception, PerceptionType, TriggerMode


class PerceptionManager:
    """
    Perception manager

    Responsibilities:
    - Manage all sensors
    - Collect perception input
    - Five-step perception pipeline (dedup, classify, intent recognition, priority assessment, fusion)
    - Priority queue management
    """

    def __init__(
        self,
        max_queue_size: int = 100,
    ):
        """
        Initialize perception manager

        Args:
            max_queue_size: maximum queue length
        """
        self.max_queue_size = max_queue_size

        # Sensor registry
        self._sensors: Dict[str, any] = {}

        # Perception queue (sorted by priority)
        self._queue: deque = deque()

        # Dedup cache (last 100 perceptions)
        self._dedup_cache: List[str] = []
        self._dedup_cache_size = 100

        # Statistics
        self._stats = {
            "perceived_count": 0,
            "dropped_count": 0,
            "processed_count": 0,
        }

    def register_sensor(self, name: str, sensor):
        """
        Register sensor

        Args:
            name: sensor name
            sensor: sensor instance
        """
        self._sensors[name] = sensor

    async def perceive(self) -> List[Perception]:
        """
        Collect all perception input

        Returns:
            Perception list (processed)
        """
        # 1. Collect raw perceptions
        raw_perceptions = await self._collect_perceptions()

        processed = []

        for perception in raw_perceptions:
            # 2. Dedup
            if self._is_duplicate(perception):
                continue

            # 3. Classify
            classified = self._classify(perception)

            # 4. Intent recognition
            intent = self._recognize_intent(classified)

            # 5. Priority assessment
            priority = self._assess_priority(classified, intent)

            # 6. Update perception
            perception.priority = priority
            processed.append(perception)

            # Add to queue (sorted by priority)
            self._enqueue(perception)

        # Update statistics
        self._stats["perceived_count"] += len(raw_perceptions)
        self._stats["processed_count"] += len(processed)

        return processed

    async def _collect_perceptions(self) -> List[Perception]:
        """
        Collect perception input from all sensors

        Returns:
            Raw perception list
        """
        perceptions = []

        for name, sensor in self._sensors.items():
            try:
                # Get sensor trigger mode
                trigger_mode = getattr(sensor, 'trigger_mode', TriggerMode.POLL)

                if trigger_mode == TriggerMode.POLL:
                    # Polling mode
                    if hasattr(sensor, 'enabled') and not sensor.enabled:
                        continue

                    perception = await sensor.sense()
                    if perception:
                        perceptions.append(perception)

                elif trigger_mode == TriggerMode.EVENT:
                    # Event mode (sensor pushes actively)
                    pass  # Sensor pushes perception via callback

                # Hybrid mode not yet implemented
            except Exception as e:
                # Log error but continue processing other sensors
                pass

        return perceptions

    def _is_duplicate(self, perception: Perception) -> bool:
        """
        Check if duplicate

        Args:
            perception: Perception

        Returns:
            Whether duplicate
        """
        # Generate perception fingerprint
        fingerprint = f"{perception.type}:{str(perception.data)}"

        if fingerprint in self._dedup_cache:
            self._stats["dropped_count"] += 1
            return True

        # Add to cache
        self._dedup_cache.append(fingerprint)
        if len(self._dedup_cache) > self._dedup_cache_size:
            self._dedup_cache.pop(0)

        return False

    def _classify(self, perception: Perception) -> Perception:
        """
        Classify perception

        Args:
            perception: Perception

        Returns:
            Classified perception
        """
        # Simplified: classify by type
        # Actual implementation can use LLM for smarter classification
        return perception

    def _recognize_intent(self, perception: Perception) -> str:
        """
        Intent recognition

        Args:
            perception: Perception

        Returns:
            intent (e.g.: query, command, notification)
        """
        # Simplified: infer intent from perception type
        intent_map = {
            PerceptionType.TEXT.value: "query",
            PerceptionType.AUDIO.value: "query",
            PerceptionType.VIDEO.value: "query",
            PerceptionType.IMAGE.value: "query",
            PerceptionType.SENSOR.value: "notification",
            PerceptionType.EVENT.value: "notification",
        }
        return intent_map.get(perception.type, "unknown")

    def _assess_priority(self, perception: Perception, intent: str) -> int:
        """
        Assess priority

        Args:
            perception: Perception
            intent: intent

        Returns:
            priority (0=normal, 1=important, 2=urgent)
        """
        # Simplified: determine priority based on intent
        if intent == "notification":
            return 1  # important
        elif perception.type == PerceptionType.SENSOR.value and perception.data.get("urgent"):
            return 2  # urgent
        else:
            return 0  # normal

    def _enqueue(self, perception: Perception):
        """
        Add to priority queue

        Args:
            perception: Perception
        """
        # Use bisect to insert in O(n) instead of sorting entire queue O(n log n).
        # _queue is maintained in descending priority order.
        keys = [-p.priority for p in self._queue]
        idx = bisect.bisect_right(keys, -perception.priority)
        self._queue.insert(idx, perception)

        # Limit queue length
        if len(self._queue) > self.max_queue_size:
            self._queue.pop()  # Remove lowest priority
            self._stats["dropped_count"] += 1

    def get_stats(self) -> dict:
        """
        Get statistics

        Returns:
            Statistics
        """
        return {
            **self._stats,
            "queue_size": len(self._queue),
            "sensor_count": len(self._sensors),
            "dedup_cache_size": len(self._dedup_cache),
        }


class Sensor:
    """Sensor base class (placeholder)"""
    @property
    def perception_type(self) -> PerceptionType:
        pass

    @property
    def trigger_mode(self) -> TriggerMode:
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        return True

    async def sense(self) -> Optional[Perception]:
        """Sense once"""
        return None

    async def listen(self, callback):
        """Listen mode (placeholder)"""
        pass
