"""
自感知模块 - 感知管理器（完整版）
"""
import asyncio
from typing import List, Optional, Callable, Dict, Any
from collections import deque
from .base import Perception, PerceptionType, TriggerMode


class PerceptionManager:
    """
    感知管理器

    职责：
    - 管理所有传感器
    - 收集感知输入
    - 五步感知决策（去重、分类、意图识别、优先级评估、融合）
    - 优先级队列管理
    """

    def __init__(
        self,
        max_queue_size: int = 100,
    ):
        """
        初始化感知管理器

        Args:
            max_queue_size: 队列最大长度
        """
        self.max_queue_size = max_queue_size

        # 传感器注册表
        self._sensors: Dict[str, any] = {}

        # 感知队列（按优先级排序）
        self._queue: deque = deque()

        # 去重缓存（最近100个感知）
        self._dedup_cache: List[str] = []
        self._dedup_cache_size = 100

        # 统计信息
        self._stats = {
            "perceived_count": 0,
            "dropped_count": 0,
            "processed_count": 0,
        }

    def register_sensor(self, name: str, sensor):
        """
        注册传感器

        Args:
            name: 传感器名称
            sensor: 传感器实例
        """
        self._sensors[name] = sensor

    async def perceive(self) -> List[Perception]:
        """
        收集所有感知输入

        Returns:
            感知列表（已处理）
        """
        # 1. 收集原始感知
        raw_perceptions = await self._collect_perceptions()

        processed = []

        for perception in raw_perceptions:
            # 2. 去重
            if self._is_duplicate(perception):
                continue

            # 3. 分类
            classified = self._classify(perception)

            # 4. 意图识别
            intent = self._recognize_intent(classified)

            # 5. 优先级评估
            priority = self._assess_priority(classified, intent)

            # 6. 更新感知
            perception.priority = priority
            processed.append(perception)

            # 加入队列（按优先级排序）
            self._enqueue(perception)

        # 更新统计
        self._stats["perceived_count"] += len(raw_perceptions)
        self._stats["processed_count"] += len(processed)

        return processed

    async def _collect_perceptions(self) -> List[Perception]:
        """
        收集所有传感器的感知输入

        Returns:
            原始感知列表
        """
        perceptions = []

        for name, sensor in self._sensors.items():
            try:
                # 获取传感器触发模式
                trigger_mode = getattr(sensor, 'trigger_mode', TriggerMode.POLL)

                if trigger_mode == TriggerMode.POLL:
                    # 轮询模式
                    if hasattr(sensor, 'enabled') and not sensor.enabled:
                        continue

                    perception = await sensor.sense()
                    if perception:
                        perceptions.append(perception)

                elif trigger_mode == TriggerMode.EVENT:
                    # 事件模式（由传感器主动调用）
                    pass  # 传感器会通过回调推送感知

                # HYBRID模式暂不实现
            except Exception as e:
                # 记录错误但继续处理其他传感器
                pass

        return perceptions

    def _is_duplicate(self, perception: Perception) -> bool:
        """
        检查是否重复

        Args:
            perception: 感知

        Returns:
            是否重复
        """
        # 生成感知指纹
        fingerprint = f"{perception.type}:{str(perception.data)}"

        if fingerprint in self._dedup_cache:
            self._stats["dropped_count"] += 1
            return True

        # 添加到缓存
        self._dedup_cache.append(fingerprint)
        if len(self._dedup_cache) > self._dedup_cache_size:
            self._dedup_cache.pop(0)

        return False

    def _classify(self, perception: Perception) -> Perception:
        """
        分类感知

        Args:
            perception: 感知

        Returns:
            分类后的感知
        """
        # 简化版：根据类型分类
        # 实际实现可以使用LLM进行更智能的分类
        return perception

    def _recognize_intent(self, perception: Perception) -> str:
        """
        意图识别

        Args:
            perception: 感知

        Returns:
            意图（如：query、command、notification）
        """
        # 简化版：根据感知类型推断意图
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
        评估优先级

        Args:
            perception: 感知
            intent: 意图

        Returns:
            优先级（0=普通，1=重要，2=紧急）
        """
        # 简化版：根据意图判断优先级
        if intent == "notification":
            return 1  # 重要
        elif perception.type == PerceptionType.SENSOR.value and perception.data.get("urgent"):
            return 2  # 紧急
        else:
            return 0  # 普通

    def _enqueue(self, perception: Perception):
        """
        加入优先级队列

        Args:
            perception: 感知
        """
        self._queue.append(perception)
        # 按优先级排序（降序）
        self._queue = deque(
            sorted(self._queue, key=lambda p: p.priority, reverse=True)
        )

        # 限制队列长度
        if len(self._queue) > self.max_queue_size:
            self._queue.pop()  # 移除优先级最低的
            self._stats["dropped_count"] += 1

    def get_stats(self) -> dict:
        """
        获取统计信息

        Returns:
            统计信息
        """
        return {
            **self._stats,
            "queue_size": len(self._queue),
            "sensor_count": len(self._sensors),
            "dedup_cache_size": len(self._dedup_cache),
        }


class Sensor:
    """传感器基类（占位）"""
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
        """感知一次"""
        return None

    async def listen(self, callback):
        """监听模式（占位）"""
        pass
