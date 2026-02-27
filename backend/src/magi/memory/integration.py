"""
Memory Integration Module - Memory Integration Module

Internal note.
- L1: RawEventStore - Raw event Storage
- L2: EventRelationStore - event Relation Graph
- L3: eventEmbeddingStore - Semantic Embeddings
- L4: SummaryStore - Time Summaries
- L5: CapabilityMemory - Capability Extraction

Design Principles：
Internal note.
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

# UnifiedMemoryStore is defined in __init__.py
from . import UnifiedMemoryStore
from ..events.events import Event, EventTypes, BusinessEventTypes
from ..events.backend import MessageBusBackend

logger = logging.getLogger(__name__)


@dataclass
class MemoryIntegrationConfig:
    """memory集成Configuration"""

    # Internal note.
    enable_l1_raw: bool = True
    enable_l2_relations: bool = True
    enable_l3_embeddings: bool = True
    enable_l4_summaries: bool = True
    enable_l5_capabilities: bool = True

    # L3 embeddinggenerationConfiguration
    async_embeddings: bool = True
    embedding_queue_size: int = 100

    # Internal note.
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
    # Internal note.
    l1_event_whitelist: Set[str] = field(default_factory=lambda: {
        EventTypes.USER_MESSAGE,      # userInput → convert为 user_input
        EventTypes.ACTION_EXECUTED,   # actionExecute → convert为 AI_RESPONSE 或 TOOL_INVOKED
        EventTypes.TASK_COMPLETED,    # 任务complete
        EventTypes.TASK_FAILED,       # 任务failure
        EventTypes.ERROR_OCCURRED,    # 只record level=error 的critical error
    })

    # Internal note.
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

    # Internal note.
    l1_error_min_level: int = 3  # EventLevel.ERROR = 3

    # is notEnableeventtypeconvert（user_MESSAGE → user_input）
    l1_enable_event_transform: bool = True

    # Internal note.
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
    Internal note.

    Internal note.
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
            Internal note.
        """
        self.unified_memory = unified_memory
        self.message_bus = message_bus
        self.config = config or MemoryIntegrationConfig()

        # Internal note.
        self._running = False
        self._subscription_ids: List[str] = []

        # L3 asynchronotttusembeddingprocess
        self._embedding_queue: asyncio.Queue = None
        self._embedding_task: asyncio.Task = None
        self._embedding_event_ids: Set[str] = set()  # 用于去重

        # Internal note.
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

        # Internal note.
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

        # Internal note.
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

        # Internal note.
        if self._embedding_task:
            self._embedding_task.cancel()
            try:
                await self._embedding_task
            except asyncio.CancelledError:
                pass
            logger.info("L3 embedding processor stopped")

        # Internal note.
        if self._summary_task:
            self._summary_task.cancel()
            try:
                await self._summary_task
            except asyncio.CancelledError:
                pass
            logger.info("L4 summary generator stopped")

        # Internal note.
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

    def _should_store_l1_event(self, event: Event) -> bool:
        """
        Internal note.

        Internal note.
        Internal note.
        Internal note.
        Internal note.
        """
        event_type = event.type

        # Internal note.
        if event_type in self.config.l1_event_blacklist:
            logger.debug(f"L1 filtered (blacklist): {event_type}")
            return False

        # Internal note.
        if event_type == EventTypes.ERROR_OCCURRED:
            level_value = event.level.value if hasattr(event.level, 'value') else event.level
            if level_value < self.config.l1_error_min_level:
                logger.debug(f"L1 filtered (error level {level_value} < {self.config.l1_error_min_level}): {event_type}")
                return False

        # Internal note.
        if self.config.l1_event_whitelist:
            if event_type not in self.config.l1_event_whitelist:
                logger.debug(f"L1 filtered (not in whitelist): {event_type}")
                return False

        return True

    def _transform_to_business_event(self, event: Event) -> Event:
        """
        Internal note.

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

        # Internal note.
        elif event_type == EventTypes.ACTION_EXECUTED:
            data = event.data if isinstance(event.data, dict) else {}
            action_type = data.get("action_type", "")

            if action_type == "ChatResponseAction":
                # Internal note.
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
                # Internal note.
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

        # error_OCCURRED → system_error（critical error）
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

        # Internal note.
        return event

    async def _handle_event(self, event: Event):
        """
        Internal note.

        Internal note.

        Args:
            event: eventObject（event type）
        """
        try:
            self._stats["events_received"] += 1
            logger.info(f"📥 event received | type: {event.type} | source: {event.source} | Correlation: {event.correlation_id[:8] if event.correlation_id else 'None'}...")

            # Internal note.
            event_id = event.correlation_id or str(uuid.uuid4())

            # Internal note.
            correlation_id = event.correlation_id
            if correlation_id:
                if correlation_id not in self._correlation_tracker:
                    self._correlation_tracker[correlation_id] = []
                self._correlation_tracker[correlation_id].append(event_id)

            # Internal note.
            if self.config.enable_l1_raw:
                # Internal note.
                if self._should_store_l1_event(event):
                    # Internal note.
                    business_event = self._transform_to_business_event(event)
                    await self._store_l1_event(business_event)
                else:
                    self._stats["l1_filtered"] += 1
                    logger.debug(f"L1 skipped: {event.type}")

            # Internal note.
            if self.config.enable_l2_relations and self.config.auto_extract_relations:
                await self._extract_l2_relations(event, event_id)

            # L3: generationSemantic Embeddings（asynchronotttusqueue）
            if self.config.enable_l3_embeddings:
                if self.config.async_embeddings:
                    await self._queue_l3_embedding(event, event_id)
                else:
                    await self._generate_l3_embedding(event, event_id)

            # Internal note.
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

    async def _store_l1_event(self, event: Event):
        """storage原始event到 L1 层"""
        try:
            event_id = await self.unified_memory.l1_raw.store(event)
            self._stats["l1_stored"] += 1
            logger.debug(f"L1 event stored | type: {event.type} | id: {event_id[:8]}...")
        except Exception as e:
            logger.error(f"L1 storage failed for event type {event.type}: {e}", exc_info=True)

    # Internal note.

    async def _extract_l2_relations(self, event: Event, event_id: str):
        """提取eventrelationship到 L2 层"""
        try:
            event_type = event.type
            correlation_id = event.correlation_id

            # Internal note.
            event_dict = {
                "id": event_id,
                "type": event_type,
                "data": event.data if isinstance(event.data, dict) else {"value": event.data},
                "timestamp": event.timestamp,
                "source": event.source,
                "correlation_id": correlation_id,
            }

            # Internal note.
            self.unified_memory.l2_relations.add_event(event_id, event_dict)

            # Internal note.
            relations_extracted = 0

            # Internal note.
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

            # Internal note.
            if event_type == EventTypes.PERCEPTION_PROCESSED:
                # Internal note.
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
                # Internal note.
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

            # Internal note.
            user_id = self._extract_user_id_from_event(event)
            if user_id:
                # Internal note.
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

            # Internal note.
            if relations_extracted > 0:
                self.unified_memory.l2_relations._save_to_disk()

        except Exception as e:
            logger.error(f"L2 relation extraction failed: {e}")

    def _extract_user_id_from_event(self, event: Event) -> Optional[str]:
        """从event中提取user id"""
        # Internal note.
        if isinstance(event.data, dict):
            return event.data.get("user_id")
        # Internal note.
        if isinstance(event.metadata, dict):
            return event.metadata.get("user_id")
        return None

    # ==================== L3: Semantic Embeddingsgeneration ====================

    async def _queue_l3_embedding(self, event: Event, event_id: str):
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

    async def _generate_l3_embedding(self, event: Event, event_id: str):
        """直接generation L3 embedding（synchronotttus）"""
        try:
            # Internal note.
            text = self._extract_text_from_event(event)
            if not text:
                return

            await self.unified_memory.l3_embeddings.add_event(
                event_id=event_id,
                text=text,
                metadata={"event_type": event.type},
            )
            self._stats["l3_embeddings_generated"] += 1

            # Internal note.
            self.unified_memory.l3_embeddings._save_to_disk()

        except Exception as e:
            logger.error(f"L3 embedding generation failed: {e}")

    async def _embedding_processor(self):
        """
        Internal note.

        Internal note.
        """
        logger.info("L3 embedding processor running")

        while self._running:
            try:
                # Internal note.
                event = await asyncio.wait_for(
                    self._embedding_queue.get(),
                    timeout=1.0
                )

                # Internal note.
                event_id = event.correlation_id or str(uuid.uuid4())
                await self._generate_l3_embedding(event, event_id)

                # Internal note.
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

    def _cache_l4_event(self, event: Event):
        """将eventadd到 L4 summarycache"""
        try:
            # Internal note.
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
        Internal note.

        Internal note.
        """
        logger.info("L4 summary generator running")

        while self._running:
            try:
                # Internal note.
                await asyncio.sleep(self.config.summary_interval_minutes * 60)

                # Internal note.
                for period_type in ["hour", "day"]:
                    period_key = self.unified_memory.l4_summaries._get_period_key(
                        time.time(), period_type
                    )

                    # Internal note.
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

    # ==================== L5: Capability Extraction ====================

    async def _handle_l5_capability(self, event: Event):
        """process L5 capabilityrecordand提取"""
        try:
            event_type = event.type

            # Internal note.
            if event_type == EventTypes.TASK_COMPLETED:
                self._record_task_capability(event)
            elif event_type == EventTypes.ACTION_EXECUTED:
                self._record_action_attempt(event)

        except Exception as e:
            logger.error(f"L5 capability handling failed: {e}")

    def _record_task_capability(self, event: Event):
        """record任务complete到capabilitymemory"""
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
        """recordactionExecute尝试"""
        data = event.data if isinstance(event.data, dict) else {}
        action_type = data.get("action_type", "")

        # Internal note.
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

    # Internal note.

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
