"""
Memory Integration Module - Memory Integration Module

将 LoopEngine event自动分发到 L1-L5 五层memoryarchitecture：
- L1: RaweventStore - Raw event Storage
- L2: eventRelationStore - event Relation Graph
- L3: eventEmbeddingStore - Semantic Embeddings
- L4: SummaryStore - Time Summaries
- L5: CapabilityMemory - Capability Extraction

Design Principles：
1. Minimal intrusion - 不修改 LoopEngine core逻辑
2. Async priority - Memory operations run in background, do not block main chain
3. Configurable - Each layer can be independently enabled/Disable
4. Graceful degradation - Failure in one layer does not affect other layers or main chain
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
from ..events.events import event, eventtypes, Businesseventtypes
from ..events.backend import MessageBusBackend

logger = logging.getLogger(__name__)


@dataclass
class MemoryIntegrationConfig:
    """memory集成Configuration"""

    # L1-L5 层级Enableswitch
    enable_l1_raw: bool = True
    enable_l2_relations: bool = True
    enable_l3_embeddings: bool = True
    enable_l4_summaries: bool = True
    enable_l5_capabilities: bool = True

    # L3 embeddinggenerationConfiguration
    async_embeddings: bool = True
    embedding_queue_size: int = 100

    # L2 relationship提取Configuration
    auto_extract_relations: bool = True

    # L4 summarygenerationConfiguration
    summary_interval_minutes: int = 60
    auto_generate_summaries: bool = True

    # L5 Capability ExtractionConfiguration
    capability_min_attempts: int = 3
    capability_min_success_rate: float = 0.7
    capability_blacklist_threshold: float = 0.3
    capability_blacklist_min_attempts: int = 5

    # ========== L1 eventfilterConfiguration ==========
    # 要record的eventtype（白名单）
    l1_event_whitelist: Set[str] = field(default_factory=lambda: {
        eventtypes.user_MESSAGE,      # userInput → convert为 user_input
        eventtypes.ACTION_executeD,   # actionExecute → convert为 AI_RESPONSE 或 TOOL_INVOKED
        eventtypes.task_COMPLETED,    # 任务complete
        eventtypes.task_failED,       # 任务failure
        eventtypes.error_OCCURRED,    # 只record level=error 的critical error
    })

    # 要filter的eventtype（黑名单）- LoopEngine internalevent
    l1_event_blacklist: Set[str] = field(default_factory=lambda: {
        eventtypes.PERCEPTION_receiveD,
        eventtypes.PERCEPTION_processED,
        eventtypes.EXPERIENCE_STORED,
        eventtypes.LOOP_startED,
        eventtypes.LOOP_COMPLETED,
        eventtypes.LOOP_pauseD,
        eventtypes.LOOP_resumeD,
        eventtypes.LOOP_PHasE_startED,
        eventtypes.LOOP_PHasE_COMPLETED,
        eventtypes.AGENT_startED,
        eventtypes.AGENT_stopPED,
        eventtypes.STATE_CHANGED,
        eventtypes.CAPABILITY_createD,
        eventtypes.CAPABILITY_updateD,
        eventtypes.HEALTH_warnING,
        eventtypes.handler_failED,
        eventtypes.task_createD,
        eventtypes.task_assignED,
        eventtypes.task_startED,
    })

    # 只recordcritical error（level >= error）
    l1_error_min_level: int = 3  # eventlevel.error = 3

    # is notEnableeventtypeconvert（user_MESSAGE → user_input）
    l1_enable_event_transform: bool = True

    # subscribe的eventtype（保持原subscribeway）
    subscribed_events: Set[str] = field(default_factory=lambda: {
        eventtypes.user_MESSAGE,
        eventtypes.PERCEPTION_receiveD,
        eventtypes.PERCEPTION_processED,
        eventtypes.ACTION_executeD,
        eventtypes.EXPERIENCE_STORED,
        eventtypes.task_COMPLETED,
        eventtypes.error_OCCURRED,
    })


class MemoryIntegrationModule:
    """
    Memory System集成module

    作为eventsubscribe者，receive LoopEngine release的event并分发到各memory层。
    """

    def __init__(
        self,
        unified_memory: UnifiedMemoryStore,
        message_bus: MessageBusBackend,
        config: MemoryIntegrationConfig = None,
    ):
        """
        initializeMemory Integration Module

        Args:
            unified_memory: Unified Memory StorageInstance
            message_bus: message bus
            config: 集成Configuration
        """
        self.unified_memory = unified_memory
        self.message_bus = message_bus
        self.config = config or MemoryIntegrationConfig()

        # State管理
        self._running = False
        self._subscription_ids: List[str] = []

        # L3 asynchronotttusembeddingprocess
        self._embedding_queue: asyncio.Queue = None
        self._embedding_task: asyncio.Task = None
        self._embedding_event_ids: Set[str] = set()  # 用于去重

        # L4 定期summarygeneration
        self._summary_task: asyncio.Task = None

        # statisticsinfo
        self._stats = {
            "events_received": 0,
            "events_processed": 0,
            "events_failed": 0,
            "l1_stored": 0,
            "l1_filtered": 0,  # new增：被filter的event数
            "l2_relations_extracted": 0,
            "l3_embeddings_generated": 0,
            "l4_summaries_generated": 0,
            "l5_capabilities_extracted": 0,
        }

        # relatedevent追踪（用于 L2 relationship提取）
        self._correlation_tracker: Dict[str, List[str]] = {}

        logger.info("MemoryIntegrationModule initialized")

    async def start(self):
        """启动Memory Integration Module"""
        if self._running:
            logger.warning("MemoryIntegrationModule already running")
            return

        self._running = True
        logger.info("Starting MemoryIntegrationModule...")

        # initialize L3 embeddingqueue
        if self.config.enable_l3_embeddings and self.config.async_embeddings:
            self._embedding_queue = asyncio.Queue(
                maxsize=self.config.embedding_queue_size
            )
            self._embedding_task = asyncio.create_task(
                self._embedding_processor()
            )
            logger.info("L3 embedding processor started")

        # 启动 L4 定期summarygeneration
        if self.config.enable_l4_summaries and self.config.auto_generate_summaries:
            self._summary_task = asyncio.create_task(
                self._summary_generator()
            )
            logger.info("L4 summary generator started")

        # subscribeevent
        await self._subscribe_to_events()

        logger.info("MemoryIntegrationModule started successfully")

    async def stop(self):
        """stopMemory Integration Module"""
        if not self._running:
            return

        logger.info("Stopping MemoryIntegrationModule...")
        self._running = False

        # cancelsubscribe
        await self._unsubscribe_from_events()

        # stop L3 embeddingprocess器
        if self._embedding_task:
            self._embedding_task.cancel()
            try:
                await self._embedding_task
            except asyncio.Cancellederror:
                pass
            logger.info("L3 embedding processor stopped")

        # stop L4 summarygeneration器
        if self._summary_task:
            self._summary_task.cancel()
            try:
                await self._summary_task
            except asyncio.Cancellederror:
                pass
            logger.info("L4 summary generator stopped")

        # 持久化data
        await self._persist_all()

        logger.info("MemoryIntegrationModule stopped")

    async def _subscribe_to_events(self):
        """subscribe LoopEngine event"""
        for event_type in self.config.subscribed_events:
            try:
                subscription_id = await self.message_bus.subscribe(
                    event_type=event_type,
                    handler=self._handle_event,
                    propagation_mode="broadcast",
                )
                self._subscription_ids.append(subscription_id)
                logger.info(f"Subscribed to {event_type} | id: {subscription_id}")
            except Exception as e:
                logger.error(f"Failed to subscribe to {event_type}: {e}")

    async def _unsubscribe_from_events(self):
        """cancelsubscribeevent"""
        for subscription_id in self._subscription_ids:
            try:
                await self.message_bus.unsubscribe(subscription_id)
                logger.debug(f"Unsubscribed: {subscription_id}")
            except Exception as e:
                logger.error(f"Failed to unsubscribe {subscription_id}: {e}")
        self._subscription_ids.clear()

    # ==================== L1 eventfilterandconvert ====================

    def _should_store_l1_event(self, event: event) -> bool:
        """
        判断eventis not应该storage到 L1

        filter逻辑：
        1. 黑名单优先 - 直接filter LoopEngine internalevent
        2. errorevent - 只recordcritical error（level >= error）
        3. 白名单 - 只record有价Value的业务event
        """
        event_type = event.type

        # 黑名单优先：internalevent不record
        if event_type in self.config.l1_event_blacklist:
            logger.debug(f"L1 filtered (blacklist): {event_type}")
            return False

        # errorevent：只recordcritical error
        if event_type == eventtypes.error_OCCURRED:
            level_value = event.level.value if hasattr(event.level, 'value') else event.level
            if level_value < self.config.l1_error_min_level:
                logger.debug(f"L1 filtered (error level {level_value} < {self.config.l1_error_min_level}): {event_type}")
                return False

        # 白名单check：只record有价Value的event
        if self.config.l1_event_whitelist:
            if event_type not in self.config.l1_event_whitelist:
                logger.debug(f"L1 filtered (not in whitelist): {event_type}")
                return False

        return True

    def _transform_to_business_event(self, event: event) -> event:
        """
        将internaleventconvert为业务event

        convertrule：
        - user_MESSAGE → user_input
        - ACTION_executeD (ChatResponseAction) → AI_RESPONSE
        - ACTION_executeD (othertool) → TOOL_INVOKED
        - error_OCCURRED (level >= error) → system_error
        """
        if not self.config.l1_enable_event_transform:
            return event

        event_type = event.type

        # user_MESSAGE → user_input
        if event_type == eventtypes.user_MESSAGE:
            return event(
                type=Businesseventtypes.user_input,
                data=event.data,
                timestamp=event.timestamp,
                source=event.source,
                level=event.level,
                correlation_id=event.correlation_id,
                metadata=event.metadata,
            )

        # ACTION_executeD → AI_RESPONSE 或 TOOL_INVOKED
        elif event_type == eventtypes.ACTION_executeD:
            data = event.data if isinstance(event.data, dict) else {}
            action_type = data.get("action_type", "")

            if action_type == "ChatResponseAction":
                # convert为 AI_RESPONSE
                return event(
                    type=Businesseventtypes.AI_RESPONSE,
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
                # otheractionconvert为 TOOL_INVOKED
                return event(
                    type=Businesseventtypes.TOOL_INVOKED,
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

        # error_OCCURRED → system_error（critical error）
        elif event_type == eventtypes.error_OCCURRED:
            level_value = event.level.value if hasattr(event.level, 'value') else event.level
            if level_value >= self.config.l1_error_min_level:
                data = event.data if isinstance(event.data, dict) else {}
                return event(
                    type=Businesseventtypes.system_error,
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

        # otherevent不convert
        return event

    async def _handle_event(self, event: event):
        """
        processreceive到的event

        这ismain的callbackFunction，由message bus的 worker 在event发生时调用。

        Args:
            event: eventObject（event type）
        """
        try:
            self._stats["events_received"] += 1
            logger.info(f"📥 event received | type: {event.type} | source: {event.source} | Correlation: {event.correlation_id[:8] if event.correlation_id else 'None'}...")

            # 使用 correlation_id 作为event id
            event_id = event.correlation_id or str(uuid.uuid4())

            # 追踪 correlation_id 用于relationship提取
            correlation_id = event.correlation_id
            if correlation_id:
                if correlation_id not in self._correlation_tracker:
                    self._correlation_tracker[correlation_id] = []
                self._correlation_tracker[correlation_id].append(event_id)

            # L1: storage原始event（带filterandconvert）
            if self.config.enable_l1_raw:
                # checkis not应该storage到 L1
                if self._should_store_l1_event(event):
                    # convert为业务event
                    business_event = self._transform_to_business_event(event)
                    await self._store_l1_event(business_event)
                else:
                    self._stats["l1_filtered"] += 1
                    logger.debug(f"L1 skipped: {event.type}")

            # L2: 提取eventrelationship（synchronotttus）
            if self.config.enable_l2_relations and self.config.auto_extract_relations:
                await self._extract_l2_relations(event, event_id)

            # L3: generationSemantic Embeddings（asynchronotttusqueue）
            if self.config.enable_l3_embeddings:
                if self.config.async_embeddings:
                    await self._queue_l3_embedding(event, event_id)
                else:
                    await self._generate_l3_embedding(event, event_id)

            # L4: add到summarycache
            if self.config.enable_l4_summaries:
                self._cache_l4_event(event)

            # L5: processCapability Extraction
            if self.config.enable_l5_capabilities:
                await self._handle_l5_capability(event)

            self._stats["events_processed"] += 1

            logger.debug(
                f"event processed | type: {event.type} | "
                f"id: {event_id[:8]}..."
            )

        except Exception as e:
            self._stats["events_failed"] += 1
            logger.error(f"Failed to handle event {event.type}: {e}", exc_info=True)

    # ==================== L1: Raw event Storage ====================

    async def _store_l1_event(self, event: event):
        """storage原始event到 L1 层"""
        try:
            event_id = await self.unified_memory.l1_raw.store(event)
            self._stats["l1_stored"] += 1
            logger.debug(f"L1 event stored | type: {event.type} | id: {event_id[:8]}...")
        except Exception as e:
            logger.error(f"L1 storage failed for event type {event.type}: {e}", exc_info=True)

    # ==================== L2: eventrelationship提取 ====================

    async def _extract_l2_relations(self, event: event, event_id: str):
        """提取eventrelationship到 L2 层"""
        try:
            event_type = event.type
            correlation_id = event.correlation_id

            # convert event 为dictionaryformatstorage
            event_dict = {
                "id": event_id,
                "type": event_type,
                "data": event.data if isinstance(event.data, dict) else {"value": event.data},
                "timestamp": event.timestamp,
                "source": event.source,
                "correlation_id": correlation_id,
            }

            # addevent到index
            self.unified_memory.l2_relations.add_event(event_id, event_dict)

            # 提取基于rule的relationship
            relations_extracted = 0

            # 1. 同 correlation_id 的前后event建立 PRECEDE relationship
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

            # 2. 根据eventtype提取特定relationship
            if event_type == eventtypes.PERCEPTION_processED:
                # 查找同 correlation_id 的 PERCEPTION_receiveD
                if correlation_id in self._correlation_tracker:
                    for related_id in self._correlation_tracker[correlation_id]:
                        related_event = self.unified_memory.l2_relations._events.get(related_id, {})
                        if related_event.get("type") == eventtypes.PERCEPTION_receiveD:
                            self.unified_memory.l2_relations.add_relation(
                                source_event_id=related_id,
                                target_event_id=event_id,
                                relation_type="TRIGGER",
                                confidence=0.95,
                            )
                            relations_extracted += 1

            elif event_type == eventtypes.EXPERIENCE_STORED:
                # 建立与前置event的 FOLLOW relationship
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

            # 3. 提取同user/同contextrelationship
            user_id = self._extract_user_id_from_event(event)
            if user_id:
                # 查找同user的otherevent
                for other_id, other_event in self.unified_memory.l2_relations._events.items():
                    if other_id != event_id:
                        other_user = other_event.get("data", {}).get("user_id", "")
                        if other_user == user_id:
                            self.unified_memory.l2_relations.add_relation(
                                source_event_id=other_id,
                                target_event_id=event_id,
                                relation_type="SAME_user",
                                confidence=0.7,
                                metadata={"user_id": user_id},
                            )
                            relations_extracted += 1

            if relations_extracted > 0:
                self._stats["l2_relations_extracted"] += relations_extracted

            # 持久化relationshipgraph（每次有newrelationship时）
            if relations_extracted > 0:
                self.unified_memory.l2_relations._save_to_disk()

        except Exception as e:
            logger.error(f"L2 relation extraction failed: {e}")

    def _extract_user_id_from_event(self, event: event) -> Optional[str]:
        """从event中提取user id"""
        # 从 data field中查找 user_id
        if isinstance(event.data, dict):
            return event.data.get("user_id")
        # 从 metadata 中查找
        if isinstance(event.metadata, dict):
            return event.metadata.get("user_id")
        return None

    # ==================== L3: Semantic Embeddingsgeneration ====================

    async def _queue_l3_embedding(self, event: event, event_id: str):
        """将event放入 L3 embeddingqueue"""
        try:
            if self._embedding_queue and not self._embedding_queue.full():
                if event_id and event_id not in self._embedding_event_ids:
                    await self._embedding_queue.put(event)
                    self._embedding_event_ids.add(event_id)
        except asyncio.QueueFull:
            logger.warning("L3 embedding queue full, dropping event")
        except Exception as e:
            logger.error(f"L3 embedding queue failed: {e}")

    async def _generate_l3_embedding(self, event: event, event_id: str):
        """直接generation L3 embedding（synchronotttus）"""
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

            # 持久化embedding
            self.unified_memory.l3_embeddings._save_to_disk()

        except Exception as e:
            logger.error(f"L3 embedding generation failed: {e}")

    async def _embedding_processor(self):
        """
        L3 asynchronotttusembeddingprocess器（后台任务）

        从queue中getevent并generationembeddingvector
        """
        logger.info("L3 embedding processor running")

        while self._running:
            try:
                # 使用timeout避免block
                event = await asyncio.wait_for(
                    self._embedding_queue.get(),
                    timeout=1.0
                )

                # 使用 correlation_id 作为 event_id
                event_id = event.correlation_id or str(uuid.uuid4())
                await self._generate_l3_embedding(event, event_id)

                # 从去重set中Remove
                if event_id in self._embedding_event_ids:
                    self._embedding_event_ids.remove(event_id)

            except asyncio.Timeouterror:
                continue
            except asyncio.Cancellederror:
                break
            except Exception as e:
                logger.error(f"L3 embedding processor error: {e}")

        logger.info("L3 embedding processor stopped")

    def _extract_text_from_event(self, event: event) -> str:
        """从event中提取文本用于embedding"""
        parts = []

        # addeventtype
        if event.type:
            parts.append(event.type)

        # adddataContent
        data = event.data if isinstance(event.data, dict) else {}
        for key, value in data.items():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}:{value}")

        return " ".join(parts) if parts else ""

    # ==================== L4: summarycache ====================

    def _cache_l4_event(self, event: event):
        """将eventadd到 L4 summarycache"""
        try:
            # convert为dictionaryformat
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
        L4 定期summarygeneration器（后台任务）

        每隔 summary_interval_minutes run一次
        """
        logger.info("L4 summary generator running")

        while self._running:
            try:
                # 等待指定interval
                await asyncio.sleep(self.config.summary_interval_minutes * 60)

                # generation各级summary
                for period_type in ["hour", "day"]:
                    period_key = self.unified_memory.l4_summaries._get_period_key(
                        time.time(), period_type
                    )

                    # checkis not需要generation
                    if period_key not in self.unified_memory.l4_summaries._summaries[period_type]:
                        summary = self.unified_memory.l4_summaries.generate_summary(
                            period_type, period_key
                        )
                        if summary:
                            self._stats["l4_summaries_generated"] += 1
                            logger.info(f"Summary generated: {period_type}/{period_key}")

            except asyncio.Cancellederror:
                break
            except Exception as e:
                logger.error(f"L4 summary generator error: {e}")

        logger.info("L4 summary generator stopped")

    # ==================== L5: Capability Extraction ====================

    async def _handle_l5_capability(self, event: event):
        """process L5 capabilityrecordand提取"""
        try:
            event_type = event.type

            # 只process特定eventtype
            if event_type == eventtypes.task_COMPLETED:
                self._record_task_capability(event)
            elif event_type == eventtypes.ACTION_executeD:
                self._record_action_attempt(event)

        except Exception as e:
            logger.error(f"L5 capability handling failed: {e}")

    def _record_task_capability(self, event: event):
        """record任务complete到capabilitymemory"""
        data = event.data if isinstance(event.data, dict) else {}
        self.unified_memory.l5_capabilities.record_attempt(
            task_id=data.get("task_id", "unknotttwn"),
            context=event.metadata or {},
            action=data.get("action", {}),
            success=data.get("success", True),
            duration=data.get("duration", 0.0),
            error=data.get("error"),
        )

    def _record_action_attempt(self, event: event):
        """recordactionExecute尝试"""
        data = event.data if isinstance(event.data, dict) else {}
        action_type = data.get("action_type", "")

        # 将actionExecuterecord为任务尝试
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

    # ==================== 持久化andstatistics ====================

    async def _persist_all(self):
        """持久化all层级的data"""
        try:
            # L2: saverelationshipgraph
            if self.config.enable_l2_relations:
                self.unified_memory.l2_relations._save_to_disk()

            # L3: saveembedding
            if self.config.enable_l3_embeddings:
                self.unified_memory.l3_embeddings._save_to_disk()

            # L4: savesummary
            if self.config.enable_l4_summaries:
                self.unified_memory.l4_summaries._save_to_disk()

            # L5: savecapability
            if self.config.enable_l5_capabilities:
                self.unified_memory.l5_capabilities._save_to_disk()

            logger.info("All memory layers persisted")

        except Exception as e:
            logger.error(f"Failed to persist memory layers: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """getstatisticsinfo"""
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
        """手动generationallpending的summary"""
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
