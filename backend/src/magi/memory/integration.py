"""
记忆集成模块 - Memory Integration Module

将 LoopEngine 事件自动分发到 L1-L5 五层记忆架构：
- L1: RawEventStore - 原始事件存储
- L2: EventRelationStore - 事件关系图
- L3: EventEmbeddingStore - 语义嵌入
- L4: SummaryStore - 时间摘要
- L5: CapabilityMemory - 能力提取

设计原则：
1. 最小侵入 - 不修改 LoopEngine 核心逻辑
2. 异步优先 - 记忆操作在后台执行，不阻塞主链路
3. 可配置 - 各层可独立启用/禁用
4. 优雅降级 - 某层失败不影响其他层和主链路
"""
import asyncio
import logging
import time
import uuid
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

# UnifiedMemoryStore is defined in __init__.py
from . import UnifiedMemoryStore
from ..events.events import Event, EventTypes, BusinessEventTypes
from ..events.backend import MessageBusBackend

logger = logging.getLogger(__name__)


@dataclass
class MemoryIntegrationConfig:
    """记忆集成配置"""

    # L1-L5 层级启用开关
    enable_l1_raw: bool = True
    enable_l2_relations: bool = True
    enable_l3_embeddings: bool = True
    enable_l4_summaries: bool = True
    enable_l5_capabilities: bool = True

    # L3 嵌入生成配置
    async_embeddings: bool = True
    embedding_queue_size: int = 100

    # L2 关系提取配置
    auto_extract_relations: bool = True

    # L4 摘要生成配置
    summary_interval_minutes: int = 60
    auto_generate_summaries: bool = True

    # L5 能力提取配置
    capability_min_attempts: int = 3
    capability_min_success_rate: float = 0.7
    capability_blacklist_threshold: float = 0.3
    capability_blacklist_min_attempts: int = 5

    # ========== L1 事件过滤配置 ==========
    # 要记录的事件类型（白名单）
    l1_event_whitelist: Set[str] = field(default_factory=lambda: {
        EventTypes.USER_MESSAGE,      # 用户输入 → 转换为 USER_INPUT
        EventTypes.ACTION_EXECUTED,   # 动作执行 → 转换为 AI_RESPONSE 或 TOOL_INVOKED
        EventTypes.TASK_COMPLETED,    # 任务完成
        EventTypes.TASK_FAILED,       # 任务失败
        EventTypes.ERROR_OCCURRED,    # 只记录 level=ERROR 的严重错误
    })

    # 要过滤的事件类型（黑名单）- LoopEngine 内部事件
    l1_event_blacklist: Set[str] = field(default_factory=lambda: {
        EventTypes.PERCEPTION_RECEIVED,
        EventTypes.PERCEPTION_PROCESSED,
        EventTypes.EXPERIENCE_STORED,
        EventTypes.LOOP_STARTED,
        EventTypes.LOOP_COMPLETED,
        EventTypes.LOOP_PAUSED,
        EventTypes.LOOP_RESUMED,
        EventTypes.LOOP_PHASE_STARTED,
        EventTypes.LOOP_PHASE_COMPLETED,
        EventTypes.AGENT_STARTED,
        EventTypes.AGENT_STOPPED,
        EventTypes.STATE_CHANGED,
        EventTypes.CAPABILITY_CREATED,
        EventTypes.CAPABILITY_UPDATED,
        EventTypes.HEALTH_WARNING,
        EventTypes.HANDLER_FAILED,
        EventTypes.TASK_CREATED,
        EventTypes.TASK_ASSIGNED,
        EventTypes.TASK_STARTED,
    })

    # 只记录严重错误（level >= ERROR）
    l1_error_min_level: int = 3  # EventLevel.ERROR = 3

    # 是否启用事件类型转换（USER_MESSAGE → USER_INPUT）
    l1_enable_event_transform: bool = True

    # 订阅的事件类型（保持原订阅方式）
    subscribed_events: Set[str] = field(default_factory=lambda: {
        EventTypes.USER_MESSAGE,
        EventTypes.PERCEPTION_RECEIVED,
        EventTypes.PERCEPTION_PROCESSED,
        EventTypes.ACTION_EXECUTED,
        EventTypes.EXPERIENCE_STORED,
        EventTypes.TASK_COMPLETED,
        EventTypes.ERROR_OCCURRED,
    })


class MemoryIntegrationModule:
    """
    记忆系统集成模块

    作为事件订阅者，接收 LoopEngine 发布的事件并分发到各记忆层。
    """

    def __init__(
        self,
        unified_memory: UnifiedMemoryStore,
        message_bus: MessageBusBackend,
        config: MemoryIntegrationConfig = None,
    ):
        """
        初始化记忆集成模块

        Args:
            unified_memory: 统一记忆存储实例
            message_bus: 消息总线
            config: 集成配置
        """
        self.unified_memory = unified_memory
        self.message_bus = message_bus
        self.config = config or MemoryIntegrationConfig()

        # 状态管理
        self._running = False
        self._subscription_ids: List[str] = []

        # L3 异步嵌入处理
        self._embedding_queue: asyncio.Queue = None
        self._embedding_task: asyncio.Task = None
        self._embedding_event_ids: Set[str] = set()  # 用于去重

        # L4 定期摘要生成
        self._summary_task: asyncio.Task = None

        # 统计信息
        self._stats = {
            "events_received": 0,
            "events_processed": 0,
            "events_failed": 0,
            "l1_stored": 0,
            "l1_filtered": 0,  # 新增：被过滤的事件数
            "l2_relations_extracted": 0,
            "l3_embeddings_generated": 0,
            "l4_summaries_generated": 0,
            "l5_capabilities_extracted": 0,
        }

        # 相关事件追踪（用于 L2 关系提取）
        self._correlation_tracker: Dict[str, List[str]] = {}

        logger.info("MemoryIntegrationModule initialized")

    async def start(self):
        """启动记忆集成模块"""
        if self._running:
            logger.warning("MemoryIntegrationModule already running")
            return

        self._running = True
        logger.info("Starting MemoryIntegrationModule...")

        # 初始化 L3 嵌入队列
        if self.config.enable_l3_embeddings and self.config.async_embeddings:
            self._embedding_queue = asyncio.Queue(
                maxsize=self.config.embedding_queue_size
            )
            self._embedding_task = asyncio.create_task(
                self._embedding_processor()
            )
            logger.info("L3 embedding processor started")

        # 启动 L4 定期摘要生成
        if self.config.enable_l4_summaries and self.config.auto_generate_summaries:
            self._summary_task = asyncio.create_task(
                self._summary_generator()
            )
            logger.info("L4 summary generator started")

        # 订阅事件
        await self._subscribe_to_events()

        logger.info("MemoryIntegrationModule started successfully")

    async def stop(self):
        """停止记忆集成模块"""
        if not self._running:
            return

        logger.info("Stopping MemoryIntegrationModule...")
        self._running = False

        # 取消订阅
        await self._unsubscribe_from_events()

        # 停止 L3 嵌入处理器
        if self._embedding_task:
            self._embedding_task.cancel()
            try:
                await self._embedding_task
            except asyncio.CancelledError:
                pass
            logger.info("L3 embedding processor stopped")

        # 停止 L4 摘要生成器
        if self._summary_task:
            self._summary_task.cancel()
            try:
                await self._summary_task
            except asyncio.CancelledError:
                pass
            logger.info("L4 summary generator stopped")

        # 持久化数据
        await self._persist_all()

        logger.info("MemoryIntegrationModule stopped")

    async def _subscribe_to_events(self):
        """订阅 LoopEngine 事件"""
        for event_type in self.config.subscribed_events:
            try:
                subscription_id = await self.message_bus.subscribe(
                    event_type=event_type,
                    handler=self._handle_event,
                    propagation_mode="broadcast",
                )
                self._subscription_ids.append(subscription_id)
                logger.info(f"Subscribed to {event_type} | ID: {subscription_id}")
            except Exception as e:
                logger.error(f"Failed to subscribe to {event_type}: {e}")

    async def _unsubscribe_from_events(self):
        """取消订阅事件"""
        for subscription_id in self._subscription_ids:
            try:
                await self.message_bus.unsubscribe(subscription_id)
                logger.debug(f"Unsubscribed: {subscription_id}")
            except Exception as e:
                logger.error(f"Failed to unsubscribe {subscription_id}: {e}")
        self._subscription_ids.clear()

    # ==================== L1 事件过滤和转换 ====================

    def _should_store_l1_event(self, event: Event) -> bool:
        """
        判断事件是否应该存储到 L1

        过滤逻辑：
        1. 黑名单优先 - 直接过滤 LoopEngine 内部事件
        2. 错误事件 - 只记录严重错误（level >= ERROR）
        3. 白名单 - 只记录有价值的业务事件
        """
        event_type = event.type

        # 黑名单优先：内部事件不记录
        if event_type in self.config.l1_event_blacklist:
            logger.debug(f"L1 filtered (blacklist): {event_type}")
            return False

        # 错误事件：只记录严重错误
        if event_type == EventTypes.ERROR_OCCURRED:
            level_value = event.level.value if hasattr(event.level, 'value') else event.level
            if level_value < self.config.l1_error_min_level:
                logger.debug(f"L1 filtered (error level {level_value} < {self.config.l1_error_min_level}): {event_type}")
                return False

        # 白名单检查：只记录有价值的事件
        if self.config.l1_event_whitelist:
            if event_type not in self.config.l1_event_whitelist:
                logger.debug(f"L1 filtered (not in whitelist): {event_type}")
                return False

        return True

    def _transform_to_business_event(self, event: Event) -> Event:
        """
        将内部事件转换为业务事件

        转换规则：
        - USER_MESSAGE → USER_INPUT
        - ACTION_EXECUTED (ChatResponseAction) → AI_RESPONSE
        - ACTION_EXECUTED (其他工具) → TOOL_INVOKED
        - ERROR_OCCURRED (level >= ERROR) → SYSTEM_ERROR
        """
        if not self.config.l1_enable_event_transform:
            return event

        event_type = event.type

        # USER_MESSAGE → USER_INPUT
        if event_type == EventTypes.USER_MESSAGE:
            return Event(
                type=BusinessEventTypes.USER_INPUT,
                data=event.data,
                timestamp=event.timestamp,
                source=event.source,
                level=event.level,
                correlation_id=event.correlation_id,
                metadata=event.metadata,
            )

        # ACTION_EXECUTED → AI_RESPONSE 或 TOOL_INVOKED
        elif event_type == EventTypes.ACTION_EXECUTED:
            data = event.data if isinstance(event.data, dict) else {}
            action_type = data.get("action_type", "")

            if action_type == "ChatResponseAction":
                # 转换为 AI_RESPONSE
                return Event(
                    type=BusinessEventTypes.AI_RESPONSE,
                    data={
                        "response": data.get("response", ""),
                        "response_time_ms": data.get("execution_time", 0),
                        "action_type": action_type,
                        "user_id": data.get("user_id"),
                        "session_id": data.get("session_id"),
                    },
                    timestamp=event.timestamp,
                    source="memory_integration",
                    level=event.level,
                    correlation_id=event.correlation_id,
                    metadata=event.metadata,
                )
            else:
                # 其他动作转换为 TOOL_INVOKED
                return Event(
                    type=BusinessEventTypes.TOOL_INVOKED,
                    data={
                        "tool_name": action_type,
                        "tool_params": data.get("params", {}),
                        "result": "success" if data.get("success", True) else "failed",
                        "execution_time_ms": data.get("execution_time", 0),
                        "error": data.get("error"),
                    },
                    timestamp=event.timestamp,
                    source="memory_integration",
                    level=event.level,
                    correlation_id=event.correlation_id,
                    metadata=event.metadata,
                )

        # ERROR_OCCURRED → SYSTEM_ERROR（严重错误）
        elif event_type == EventTypes.ERROR_OCCURRED:
            level_value = event.level.value if hasattr(event.level, 'value') else event.level
            if level_value >= self.config.l1_error_min_level:
                data = event.data if isinstance(event.data, dict) else {}
                return Event(
                    type=BusinessEventTypes.SYSTEM_ERROR,
                    data={
                        "error_code": data.get("error_code", "UNKNOWN"),
                        "error_message": data.get("error_message", str(data.get("error", ""))),
                        "affected_user_id": data.get("user_id", ""),
                        "level": level_value,
                    },
                    timestamp=event.timestamp,
                    source="memory_integration",
                    level=event.level,
                    correlation_id=event.correlation_id,
                    metadata=event.metadata,
                )

        # 其他事件不转换
        return event

    async def _handle_event(self, event: Event):
        """
        处理接收到的事件

        这是主要的回调函数，由消息总线的 worker 在事件发生时调用。

        Args:
            event: 事件对象（Event 类型）
        """
        try:
            self._stats["events_received"] += 1
            logger.info(f"📥 Event received | Type: {event.type} | Source: {event.source} | Correlation: {event.correlation_id[:8] if event.correlation_id else 'None'}...")

            # 使用 correlation_id 作为事件 ID
            event_id = event.correlation_id or str(uuid.uuid4())

            # 追踪 correlation_id 用于关系提取
            correlation_id = event.correlation_id
            if correlation_id:
                if correlation_id not in self._correlation_tracker:
                    self._correlation_tracker[correlation_id] = []
                self._correlation_tracker[correlation_id].append(event_id)

            # L1: 存储原始事件（带过滤和转换）
            if self.config.enable_l1_raw:
                # 检查是否应该存储到 L1
                if self._should_store_l1_event(event):
                    # 转换为业务事件
                    business_event = self._transform_to_business_event(event)
                    await self._store_l1_event(business_event)
                else:
                    self._stats["l1_filtered"] += 1
                    logger.debug(f"L1 skipped: {event.type}")

            # L2: 提取事件关系（同步）
            if self.config.enable_l2_relations and self.config.auto_extract_relations:
                await self._extract_l2_relations(event, event_id)

            # L3: 生成语义嵌入（异步队列）
            if self.config.enable_l3_embeddings:
                if self.config.async_embeddings:
                    await self._queue_l3_embedding(event, event_id)
                else:
                    await self._generate_l3_embedding(event, event_id)

            # L4: 添加到摘要缓存
            if self.config.enable_l4_summaries:
                self._cache_l4_event(event)

            # L5: 处理能力提取
            if self.config.enable_l5_capabilities:
                await self._handle_l5_capability(event)

            self._stats["events_processed"] += 1

            logger.debug(
                f"Event processed | Type: {event.type} | "
                f"ID: {event_id[:8]}..."
            )

        except Exception as e:
            self._stats["events_failed"] += 1
            logger.error(f"Failed to handle event {event.type}: {e}", exc_info=True)

    # ==================== L1: 原始事件存储 ====================

    async def _store_l1_event(self, event: Event):
        """存储原始事件到 L1 层"""
        try:
            event_id = await self.unified_memory.l1_raw.store(event)
            self._stats["l1_stored"] += 1
            logger.debug(f"L1 event stored | Type: {event.type} | ID: {event_id[:8]}...")
        except Exception as e:
            logger.error(f"L1 storage failed for event type {event.type}: {e}", exc_info=True)

    # ==================== L2: 事件关系提取 ====================

    async def _extract_l2_relations(self, event: Event, event_id: str):
        """提取事件关系到 L2 层"""
        try:
            event_type = event.type
            correlation_id = event.correlation_id

            # 转换 Event 为字典格式存储
            event_dict = {
                "id": event_id,
                "type": event_type,
                "data": event.data if isinstance(event.data, dict) else {"value": event.data},
                "timestamp": event.timestamp,
                "source": event.source,
                "correlation_id": correlation_id,
            }

            # 添加事件到索引
            self.unified_memory.l2_relations.add_event(event_id, event_dict)

            # 提取基于规则的关系
            relations_extracted = 0

            # 1. 同 correlation_id 的前后事件建立 PRECEDE 关系
            if correlation_id and correlation_id in self._correlation_tracker:
                related_events = self._correlation_tracker[correlation_id]
                for related_id in related_events:
                    if related_id != event_id:
                        self.unified_memory.l2_relations.add_relation(
                            source_event_id=related_id,
                            target_event_id=event_id,
                            relation_type="PRECEDE",
                            confidence=0.9,
                            metadata={"correlation_id": correlation_id},
                        )
                        relations_extracted += 1

            # 2. 根据事件类型提取特定关系
            if event_type == EventTypes.PERCEPTION_PROCESSED:
                # 查找同 correlation_id 的 PERCEPTION_RECEIVED
                if correlation_id in self._correlation_tracker:
                    for related_id in self._correlation_tracker[correlation_id]:
                        related_event = self.unified_memory.l2_relations._events.get(related_id, {})
                        if related_event.get("type") == EventTypes.PERCEPTION_RECEIVED:
                            self.unified_memory.l2_relations.add_relation(
                                source_event_id=related_id,
                                target_event_id=event_id,
                                relation_type="TRIGGER",
                                confidence=0.95,
                            )
                            relations_extracted += 1

            elif event_type == EventTypes.EXPERIENCE_STORED:
                # 建立与前置事件的 FOLLOW 关系
                if correlation_id in self._correlation_tracker:
                    for related_id in self._correlation_tracker[correlation_id]:
                        if related_id != event_id:
                            self.unified_memory.l2_relations.add_relation(
                                source_event_id=related_id,
                                target_event_id=event_id,
                                relation_type="FOLLOW",
                                confidence=0.8,
                            )
                            relations_extracted += 1

            # 3. 提取同用户/同上下文关系
            user_id = self._extract_user_id_from_event(event)
            if user_id:
                # 查找同用户的其他事件
                for other_id, other_event in self.unified_memory.l2_relations._events.items():
                    if other_id != event_id:
                        other_user = other_event.get("data", {}).get("user_id", "")
                        if other_user == user_id:
                            self.unified_memory.l2_relations.add_relation(
                                source_event_id=other_id,
                                target_event_id=event_id,
                                relation_type="SAME_USER",
                                confidence=0.7,
                                metadata={"user_id": user_id},
                            )
                            relations_extracted += 1

            if relations_extracted > 0:
                self._stats["l2_relations_extracted"] += relations_extracted

            # 持久化关系图（每次有新关系时）
            if relations_extracted > 0:
                self.unified_memory.l2_relations._save_to_disk()

        except Exception as e:
            logger.error(f"L2 relation extraction failed: {e}")

    def _extract_user_id_from_event(self, event: Event) -> Optional[str]:
        """从事件中提取用户 ID"""
        # 从 data 字段中查找 user_id
        if isinstance(event.data, dict):
            return event.data.get("user_id")
        # 从 metadata 中查找
        if isinstance(event.metadata, dict):
            return event.metadata.get("user_id")
        return None

    # ==================== L3: 语义嵌入生成 ====================

    async def _queue_l3_embedding(self, event: Event, event_id: str):
        """将事件放入 L3 嵌入队列"""
        try:
            if self._embedding_queue and not self._embedding_queue.full():
                if event_id and event_id not in self._embedding_event_ids:
                    await self._embedding_queue.put(event)
                    self._embedding_event_ids.add(event_id)
        except asyncio.QueueFull:
            logger.warning("L3 embedding queue full, dropping event")
        except Exception as e:
            logger.error(f"L3 embedding queue failed: {e}")

    async def _generate_l3_embedding(self, event: Event, event_id: str):
        """直接生成 L3 嵌入（同步）"""
        try:
            # 提取文本
            text = self._extract_text_from_event(event)
            if not text:
                return

            await self.unified_memory.l3_embeddings.add_event(
                event_id=event_id,
                text=text,
                metadata={"event_type": event.type},
            )
            self._stats["l3_embeddings_generated"] += 1

            # 持久化嵌入
            self.unified_memory.l3_embeddings._save_to_disk()

        except Exception as e:
            logger.error(f"L3 embedding generation failed: {e}")

    async def _embedding_processor(self):
        """
        L3 异步嵌入处理器（后台任务）

        从队列中获取事件并生成嵌入向量
        """
        logger.info("L3 embedding processor running")

        while self._running:
            try:
                # 使用超时避免阻塞
                event = await asyncio.wait_for(
                    self._embedding_queue.get(),
                    timeout=1.0
                )

                # 使用 correlation_id 作为 event_id
                event_id = event.correlation_id or str(uuid.uuid4())
                await self._generate_l3_embedding(event, event_id)

                # 从去重集合中移除
                if event_id in self._embedding_event_ids:
                    self._embedding_event_ids.remove(event_id)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"L3 embedding processor error: {e}")

        logger.info("L3 embedding processor stopped")

    def _extract_text_from_event(self, event: Event) -> str:
        """从事件中提取文本用于嵌入"""
        parts = []

        # 添加事件类型
        if event.type:
            parts.append(event.type)

        # 添加数据内容
        data = event.data if isinstance(event.data, dict) else {}
        for key, value in data.items():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}:{value}")

        return " ".join(parts) if parts else ""

    # ==================== L4: 摘要缓存 ====================

    def _cache_l4_event(self, event: Event):
        """将事件添加到 L4 摘要缓存"""
        try:
            # 转换为字典格式
            event_dict = {
                "id": event.correlation_id or str(uuid.uuid4()),
                "type": event.type,
                "data": event.data if isinstance(event.data, dict) else {"value": event.data},
                "timestamp": event.timestamp,
                "source": event.source,
                "level": event.level.value if hasattr(event.level, 'value') else event.level,
                "correlation_id": event.correlation_id,
                "metadata": event.metadata,
            }
            self.unified_memory.l4_summaries.add_event(event_dict)
        except Exception as e:
            logger.error(f"L4 event caching failed: {e}")

    async def _summary_generator(self):
        """
        L4 定期摘要生成器（后台任务）

        每隔 summary_interval_minutes 运行一次
        """
        logger.info("L4 summary generator running")

        while self._running:
            try:
                # 等待指定间隔
                await asyncio.sleep(self.config.summary_interval_minutes * 60)

                # 生成各级摘要
                for period_type in ["hour", "day"]:
                    period_key = self.unified_memory.l4_summaries._get_period_key(
                        time.time(), period_type
                    )

                    # 检查是否需要生成
                    if period_key not in self.unified_memory.l4_summaries._summaries[period_type]:
                        summary = self.unified_memory.l4_summaries.generate_summary(
                            period_type, period_key
                        )
                        if summary:
                            self._stats["l4_summaries_generated"] += 1
                            logger.info(f"Summary generated: {period_type}/{period_key}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"L4 summary generator error: {e}")

        logger.info("L4 summary generator stopped")

    # ==================== L5: 能力提取 ====================

    async def _handle_l5_capability(self, event: Event):
        """处理 L5 能力记录和提取"""
        try:
            event_type = event.type

            # 只处理特定事件类型
            if event_type == EventTypes.TASK_COMPLETED:
                self._record_task_capability(event)
            elif event_type == EventTypes.ACTION_EXECUTED:
                self._record_action_attempt(event)

        except Exception as e:
            logger.error(f"L5 capability handling failed: {e}")

    def _record_task_capability(self, event: Event):
        """记录任务完成到能力记忆"""
        data = event.data if isinstance(event.data, dict) else {}
        self.unified_memory.l5_capabilities.record_attempt(
            task_id=data.get("task_id", "unknown"),
            context=event.metadata or {},
            action=data.get("action", {}),
            success=data.get("success", True),
            duration=data.get("duration", 0.0),
            error=data.get("error"),
        )

    def _record_action_attempt(self, event: Event):
        """记录动作执行尝试"""
        data = event.data if isinstance(event.data, dict) else {}
        action_type = data.get("action_type", "")

        # 将动作执行记录为任务尝试
        if action_type:
            self.unified_memory.l5_capabilities.record_attempt(
                task_id=f"action_{action_type}",
                context={
                    "event_type": event.type,
                    "action_type": action_type,
                },
                action={"type": action_type},
                success=data.get("success", True),
                duration=data.get("execution_time", 0.0),
                error=data.get("error"),
            )

    # ==================== 持久化和统计 ====================

    async def _persist_all(self):
        """持久化所有层级的数据"""
        try:
            # L2: 保存关系图
            if self.config.enable_l2_relations:
                self.unified_memory.l2_relations._save_to_disk()

            # L3: 保存嵌入
            if self.config.enable_l3_embeddings:
                self.unified_memory.l3_embeddings._save_to_disk()

            # L4: 保存摘要
            if self.config.enable_l4_summaries:
                self.unified_memory.l4_summaries._save_to_disk()

            # L5: 保存能力
            if self.config.enable_l5_capabilities:
                self.unified_memory.l5_capabilities._save_to_disk()

            logger.info("All memory layers persisted")

        except Exception as e:
            logger.error(f"Failed to persist memory layers: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "config": {
                "enable_l1_raw": self.config.enable_l1_raw,
                "enable_l2_relations": self.config.enable_l2_relations,
                "enable_l3_embeddings": self.config.enable_l3_embeddings,
                "enable_l4_summaries": self.config.enable_l4_summaries,
                "enable_l5_capabilities": self.config.enable_l5_capabilities,
                "async_embeddings": self.config.async_embeddings,
                "auto_extract_relations": self.config.auto_extract_relations,
                "summary_interval_minutes": self.config.summary_interval_minutes,
            },
            "subscription_count": len(self._subscription_ids),
            "queue_size": self._embedding_queue.qsize() if self._embedding_queue else 0,
        }

    async def generate_pending_summaries(self):
        """手动生成所有待处理的摘要"""
        if not self.config.enable_l4_summaries:
            return

        for period_type in ["hour", "day", "week"]:
            period_key = self.unified_memory.l4_summaries._get_period_key(
                time.time(), period_type
            )

            if period_key not in self.unified_memory.l4_summaries._summaries[period_type]:
                summary = self.unified_memory.l4_summaries.generate_summary(
                    period_type, period_key
                )
                if summary:
                    self._stats["l4_summaries_generated"] += 1

        logger.info("Pending summaries generated")


__all__ = [
    "MemoryIntegrationConfig",
    "MemoryIntegrationModule",
]
