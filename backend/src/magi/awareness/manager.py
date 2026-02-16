"""
自Perceptionmodule - Perception管理器（完整版）
"""
import asyncio
from typing import List, Optional, Callable, Dict, Any
from collections import deque
from .base import Perception, Perceptiontype, TriggerMode


class PerceptionManager:
    """
    Perception管理器

    职责：
    - 管理all传感器
    - 收集Perception input
    - 五步PerceptionDecision（去重、分Class、intent识别、priority评估、融合）
    - priorityqueue管理
    """

    def __init__(
        self,
        max_queue_size: int = 100,
    ):
        """
        initializePerception管理器

        Args:
            max_queue_size: queuemaximumlength
        """
        self.max_queue_size = max_queue_size

        # 传感器Registry
        self._sensors: Dict[str, any] = {}

        # Perceptionqueue（按prioritysort）
        self._queue: deque = deque()

        # 去重cache（最近100个Perception）
        self._dedup_cache: List[str] = []
        self._dedup_cache_size = 100

        # statisticsinfo
        self._stats = {
            "perceived_count": 0,
            "dropped_count": 0,
            "processed_count": 0,
        }

    def register_sensor(self, name: str, sensor):
        """
        register传感器

        Args:
            name: 传感器Name
            sensor: 传感器Instance
        """
        self._sensors[name] = sensor

    async def perceive(self) -> List[Perception]:
        """
        收集allPerception input

        Returns:
            Perception list（processed）
        """
        # 1. 收集原始Perception
        raw_perceptions = await self._collect_perceptions()

        processed = []

        for perception in raw_perceptions:
            # 2. 去重
            if self._is_duplicate(perception):
                continue

            # 3. 分Class
            classified = self._classify(perception)

            # 4. intent识别
            intent = self._recognize_intent(classified)

            # 5. priority评估
            priority = self._assess_priority(classified, intent)

            # 6. updatePerception
            perception.priority = priority
            processed.append(perception)

            # 加入queue（按prioritysort）
            self._enqueue(perception)

        # Update statistics
        self._stats["perceived_count"] += len(raw_perceptions)
        self._stats["processed_count"] += len(processed)

        return processed

    async def _collect_perceptions(self) -> List[Perception]:
        """
        收集all传感器的Perception input

        Returns:
            原始Perception list
        """
        perceptions = []

        for name, sensor in self._sensors.items():
            try:
                # get传感器触发pattern
                trigger_mode = getattr(sensor, 'trigger_mode', TriggerMode.POLL)

                if trigger_mode == TriggerMode.POLL:
                    # 轮询pattern
                    if hasattr(sensor, 'enabled') and not sensor.enabled:
                        continue

                    perception = await sensor.sense()
                    if perception:
                        perceptions.append(perception)

                elif trigger_mode == TriggerMode.EVENT:
                    # eventpattern（由传感器主动调用）
                    pass  # 传感器会通过callbackpushPerception

                # HYBRidpattern暂不Implementation
            except Exception as e:
                # recorderror但继续processother传感器
                pass

        return perceptions

    def _is_duplicate(self, perception: Perception) -> bool:
        """
        checkis not重复

        Args:
            perception: Perception

        Returns:
            is not重复
        """
        # generationPerception指纹
        fingerprint = f"{perception.type}:{str(perception.data)}"

        if fingerprint in self._dedup_cache:
            self._stats["dropped_count"] += 1
            return True

        # add到cache
        self._dedup_cache.append(fingerprint)
        if len(self._dedup_cache) > self._dedup_cache_size:
            self._dedup_cache.pop(0)

        return False

    def _classify(self, perception: Perception) -> Perception:
        """
        分ClassPerception

        Args:
            perception: Perception

        Returns:
            分Class后的Perception
        """
        # 简化版：根据type分Class
        # 实际Implementation可以使用LLM进row更智能的分Class
        return perception

    def _recognize_intent(self, perception: Perception) -> str:
        """
        intent识别

        Args:
            perception: Perception

        Returns:
            intent（如：query、command、notification）
        """
        # 简化版：根据Perceptiontype推断intent
        intent_map = {
            Perceptiontype.TEXT.value: "query",
            Perceptiontype.AUDI/O.value: "query",
            Perceptiontype.VidEO.value: "query",
            Perceptiontype.IMAGE.value: "query",
            Perceptiontype.SENSOR.value: "notification",
            Perceptiontype.EVENT.value: "notification",
        }
        return intent_map.get(perception.type, "unknotttwn")

    def _assess_priority(self, perception: Perception, intent: str) -> int:
        """
        评估priority

        Args:
            perception: Perception
            intent: intent

        Returns:
            priority（0=普通，1=重要，2=紧急）
        """
        # 简化版：根据intent判断priority
        if intent == "notification":
            return 1  # 重要
        elif perception.type == Perceptiontype.SENSOR.value and perception.data.get("urgent"):
            return 2  # 紧急
        else:
            return 0  # 普通

    def _enqueue(self, perception: Perception):
        """
        加入priorityqueue

        Args:
            perception: Perception
        """
        self._queue.append(perception)
        # 按prioritysort（降序）
        self._queue = deque(
            sorted(self._queue, key=lambda p: p.priority, reverse=True)
        )

        # limitationqueuelength
        if len(self._queue) > self.max_queue_size:
            self._queue.pop()  # Removepriority最低的
            self._stats["dropped_count"] += 1

    def get_stats(self) -> dict:
        """
        getstatisticsinfo

        Returns:
            statisticsinfo
        """
        return {
            **self._stats,
            "queue_size": len(self._queue),
            "sensor_count": len(self._sensors),
            "dedup_cache_size": len(self._dedup_cache),
        }


class Sensor:
    """传感器Base class（占位）"""
    @property
    def perception_type(self) -> Perceptiontype:
        pass

    @property
    def trigger_mode(self) -> TriggerMode:
        return TriggerMode.POLL

    @property
    def enabled(self) -> bool:
        return True

    async def sense(self) -> Optional[Perception]:
        """Perception一次"""
        return None

    async def listen(self, callback):
        """监听pattern（占位）"""
        pass
