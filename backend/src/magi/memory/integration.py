"""Memory integration pipeline that fans runtime events into L1-L5 memory layers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..events.backend import MessageBusBackend
from ..events.events import BusinessEventTypes, Event, EventTypes
from . import UnifiedMemoryStore

logger = logging.getLogger(__name__)
WORKER_AGENT_EVENT_TYPES: Set[str] = {
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
}


@dataclass
class MemoryIntegrationConfig:
    """Configuration for MemoryIntegrationModule."""

    enable_l1_raw: bool = True
    enable_l2_relations: bool = True
    enable_l3_embeddings: bool = True
    enable_l4_summaries: bool = True
    enable_l5_capabilities: bool = True

    async_embeddings: bool = True
    embedding_queue_size: int = 200

    auto_extract_relations: bool = True
    summary_interval_minutes: int = 60
    auto_generate_summaries: bool = True

    capability_min_attempts: int = 3
    capability_min_success_rate: float = 0.7
    capability_blacklist_threshold: float = 0.3
    capability_blacklist_min_attempts: int = 5

    l1_event_whitelist: Set[str] = field(
        default_factory=lambda: {
            EventTypes.USER_MESSAGE,
            EventTypes.ACTION_EXECUTED,
            EventTypes.TASK_COMPLETED,
            EventTypes.TASK_FAILED,
            EventTypes.ERROR_OCCURRED,
            *WORKER_AGENT_EVENT_TYPES,
        }
    )
    l1_event_blacklist: Set[str] = field(
        default_factory=lambda: {
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
        }
    )
    l1_error_min_level: int = 3
    l1_enable_event_transform: bool = True

    subscribed_events: Set[str] = field(
        default_factory=lambda: {
            EventTypes.USER_MESSAGE,
            EventTypes.PERCEPTION_RECEIVED,
            EventTypes.PERCEPTION_PROCESSED,
            EventTypes.ACTION_EXECUTED,
            EventTypes.EXPERIENCE_STORED,
            EventTypes.TASK_COMPLETED,
            EventTypes.TASK_FAILED,
            EventTypes.ERROR_OCCURRED,
            *WORKER_AGENT_EVENT_TYPES,
        }
    )


class MemoryIntegrationModule:
    """Bridges message bus events into the unified memory layers."""

    def __init__(
        self,
        unified_memory: UnifiedMemoryStore,
        message_bus: MessageBusBackend,
        config: Optional[MemoryIntegrationConfig] = None,
    ):
        self.unified_memory = unified_memory
        self.message_bus = message_bus
        self.config = config or MemoryIntegrationConfig()

        self._running = False
        self._subscription_ids: List[str] = []

        self._embedding_queue: Optional[asyncio.Queue[Tuple[Event, str]]] = None
        self._embedding_task: Optional[asyncio.Task] = None
        self._summary_task: Optional[asyncio.Task] = None

        self._correlation_tracker: Dict[str, List[str]] = {}
        self._event_index: Dict[str, Dict[str, Any]] = {}

        self._stats: Dict[str, int] = {
            "events_received": 0,
            "events_processed": 0,
            "events_failed": 0,
            "l1_stored": 0,
            "l1_filtered": 0,
            "l2_relations_extracted": 0,
            "l3_embeddings_generated": 0,
            "l4_summaries_generated": 0,
            "l5_capabilities_extracted": 0,
        }

    async def start(self) -> None:
        if self._running:
            return

        self._running = True

        if self.config.enable_l3_embeddings and self.config.async_embeddings:
            self._embedding_queue = asyncio.Queue(maxsize=self.config.embedding_queue_size)
            self._embedding_task = asyncio.create_task(self._embedding_processor())

        if self.config.enable_l4_summaries and self.config.auto_generate_summaries:
            self._summary_task = asyncio.create_task(self._summary_generator())

        await self._subscribe_to_events()
        logger.info("MemoryIntegrationModule started")

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        await self._unsubscribe_from_events()

        for task in (self._embedding_task, self._summary_task):
            if not task:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._persist_all()
        logger.info("MemoryIntegrationModule stopped")

    async def _subscribe_to_events(self) -> None:
        for event_type in self.config.subscribed_events:
            try:
                subscription_id = await self.message_bus.subscribe(
                    event_type=event_type,
                    handler=self._handle_event,
                    propagation_mode="broadcast",
                )
                self._subscription_ids.append(subscription_id)
            except Exception as exc:
                logger.warning("Failed to subscribe to %s: %s", event_type, exc)

    async def _unsubscribe_from_events(self) -> None:
        for subscription_id in self._subscription_ids:
            try:
                await self.message_bus.unsubscribe(subscription_id)
            except Exception as exc:
                logger.warning("Failed to unsubscribe %s: %s", subscription_id, exc)
        self._subscription_ids.clear()

    async def _handle_event(self, event: Event) -> None:
        self._stats["events_received"] += 1
        event_id = str(uuid.uuid4())

        try:
            if event.correlation_id:
                self._correlation_tracker.setdefault(event.correlation_id, []).append(event_id)

            if self.config.enable_l1_raw:
                await self._maybe_store_l1(event)

            if self.config.enable_l2_relations and self.config.auto_extract_relations:
                await self._extract_l2_relations(event, event_id)

            if self.config.enable_l3_embeddings and self.unified_memory.l3_embeddings:
                if self.config.async_embeddings and self._embedding_queue:
                    await self._queue_l3_embedding(event, event_id)
                else:
                    await self._generate_l3_embedding(event, event_id)

            if self.config.enable_l4_summaries and self.unified_memory.l4_summaries:
                self._cache_l4_event(event, event_id)

            if self.config.enable_l5_capabilities and self.unified_memory.l5_capabilities:
                self._handle_l5_capability(event)

            self._stats["events_processed"] += 1
        except Exception as exc:
            self._stats["events_failed"] += 1
            logger.exception("Failed to process event %s: %s", event.type, exc)

    async def _maybe_store_l1(self, event: Event) -> None:
        if not self._should_store_l1_event(event):
            self._stats["l1_filtered"] += 1
            return

        business_event = self._transform_to_business_event(event)
        await self.unified_memory.l1_raw.store(business_event)
        self._stats["l1_stored"] += 1

    def _should_store_l1_event(self, event: Event) -> bool:
        event_type = event.type

        if event_type in self.config.l1_event_blacklist:
            return False

        if event_type == EventTypes.ERROR_OCCURRED:
            level_value = event.level.value if hasattr(event.level, "value") else int(event.level)
            if level_value < self.config.l1_error_min_level:
                return False

        if self.config.l1_event_whitelist and event_type not in self.config.l1_event_whitelist:
            return False

        return True

    def _transform_to_business_event(self, event: Event) -> Event:
        if not self.config.l1_enable_event_transform:
            return event

        if event.type == EventTypes.USER_MESSAGE:
            return Event(
                type=BusinessEventTypes.USER_INPUT,
                data=event.data,
                timestamp=event.timestamp,
                source=event.source,
                level=event.level,
                correlation_id=event.correlation_id,
                metadata=event.metadata,
            )

        if event.type == EventTypes.ACTION_EXECUTED:
            data = event.data if isinstance(event.data, dict) else {}
            action_type = str(data.get("action_type", ""))
            if action_type == "ChatResponseAction":
                return Event(
                    type=BusinessEventTypes.AI_RESPONSE,
                    data={
                        "response": data.get("response", ""),
                        "response_time_ms": data.get("execution_time", 0),
                        "action_type": action_type,
                        "user_id": data.get("user_id"),
                        "session_id": data.get("session_id"),
                        "turn_id": data.get("turn_id"),
                        "orchestration_id": data.get("orchestration_id"),
                    },
                    timestamp=event.timestamp,
                    source="memory_integration",
                    level=event.level,
                    correlation_id=event.correlation_id,
                    metadata=event.metadata,
                )

            return Event(
                type=BusinessEventTypes.TOOL_INVOKED,
                data={
                    "tool_name": action_type,
                    "tool_params": data.get("params", {}),
                    "result": "success" if data.get("success", True) else "failed",
                    "execution_time_ms": data.get("execution_time", 0),
                    "error": data.get("error"),
                    "user_id": data.get("user_id"),
                    "session_id": data.get("session_id"),
                    "turn_id": data.get("turn_id"),
                    "orchestration_id": data.get("orchestration_id"),
                    "tool_call_id": data.get("tool_call_id"),
                    "iteration": data.get("iteration"),
                },
                timestamp=event.timestamp,
                source="memory_integration",
                level=event.level,
                correlation_id=event.correlation_id,
                metadata=event.metadata,
            )

        if event.type == EventTypes.ERROR_OCCURRED:
            data = event.data if isinstance(event.data, dict) else {}
            level_value = event.level.value if hasattr(event.level, "value") else int(event.level)
            return Event(
                type=BusinessEventTypes.SYSTEM_ERROR,
                data={
                    "error_code": data.get("error_code", "UNKNOWN"),
                    "error_message": data.get("error_message") or str(data.get("error", "")),
                    "affected_user_id": data.get("user_id", ""),
                    "level": level_value,
                },
                timestamp=event.timestamp,
                source="memory_integration",
                level=event.level,
                correlation_id=event.correlation_id,
                metadata=event.metadata,
            )

        return event

    async def _extract_l2_relations(self, event: Event, event_id: str) -> None:
        event_payload = {
            "id": event_id,
            "type": event.type,
            "data": event.data if isinstance(event.data, dict) else {"value": event.data},
            "timestamp": event.timestamp,
            "source": event.source,
            "correlation_id": event.correlation_id,
        }
        self.unified_memory.l2_relations.add_event(event_id, event_payload)
        self._event_index[event_id] = event_payload

        extracted = 0

        # Correlation chain relations
        correlation_id = event.correlation_id
        if correlation_id and correlation_id in self._correlation_tracker:
            related_ids = self._correlation_tracker[correlation_id]
            for related_id in related_ids:
                if related_id == event_id:
                    continue
                self.unified_memory.l2_relations.add_relation(
                    source_event_id=related_id,
                    target_event_id=event_id,
                    relation_type="PRECEDE",
                    confidence=0.9,
                    metadata={"correlation_id": correlation_id},
                )
                extracted += 1

        # Structured rule extraction
        if event.type == EventTypes.PERCEPTION_PROCESSED and correlation_id:
            for related_id in self._correlation_tracker.get(correlation_id, []):
                other = self._event_index.get(related_id, {})
                if other.get("type") == EventTypes.PERCEPTION_RECEIVED:
                    self.unified_memory.l2_relations.add_relation(
                        source_event_id=related_id,
                        target_event_id=event_id,
                        relation_type="TRIGGER",
                        confidence=0.95,
                    )
                    extracted += 1

        if event.type == EventTypes.TASK_COMPLETED and correlation_id:
            for related_id in self._correlation_tracker.get(correlation_id, []):
                other = self._event_index.get(related_id, {})
                if other.get("type") == EventTypes.TASK_STARTED:
                    self.unified_memory.l2_relations.add_relation(
                        source_event_id=related_id,
                        target_event_id=event_id,
                        relation_type="FOLLOW",
                        confidence=0.95,
                    )
                    extracted += 1

        user_id = self._extract_user_id_from_event(event)
        if user_id:
            for other_id, other_event in self.unified_memory.l2_relations._events.items():
                if other_id == event_id:
                    continue
                other_user_id = ""
                data = other_event.get("data")
                if isinstance(data, dict):
                    other_user_id = str(data.get("user_id", ""))
                if other_user_id and other_user_id == user_id:
                    self.unified_memory.l2_relations.add_relation(
                        source_event_id=other_id,
                        target_event_id=event_id,
                        relation_type="SAME_USER",
                        confidence=0.7,
                        metadata={"user_id": user_id},
                    )
                    extracted += 1

        if extracted:
            self._stats["l2_relations_extracted"] += extracted
            self.unified_memory.l2_relations._save_to_disk()

    def _extract_user_id_from_event(self, event: Event) -> Optional[str]:
        if isinstance(event.data, dict) and event.data.get("user_id"):
            return str(event.data["user_id"])
        if isinstance(event.metadata, dict) and event.metadata.get("user_id"):
            return str(event.metadata["user_id"])
        return None

    async def _queue_l3_embedding(self, event: Event, event_id: str) -> None:
        if not self._embedding_queue:
            return

        try:
            self._embedding_queue.put_nowait((event, event_id))
        except asyncio.QueueFull:
            logger.warning("Embedding queue full; dropping event %s", event_id)

    async def _generate_l3_embedding(self, event: Event, event_id: str) -> None:
        text = self._extract_text_from_event(event)
        if not text:
            return

        await self.unified_memory.l3_embeddings.add_event(
            event_id=event_id,
            text=text,
            metadata={"event_type": event.type},
        )
        self._stats["l3_embeddings_generated"] += 1

    async def _embedding_processor(self) -> None:
        while self._running:
            try:
                event, event_id = await asyncio.wait_for(self._embedding_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._generate_l3_embedding(event, event_id)
            except Exception as exc:
                logger.warning("Failed generating embedding for %s: %s", event_id, exc)

    def _extract_text_from_event(self, event: Event) -> str:
        parts = [event.type]

        if isinstance(event.data, dict):
            for key, value in event.data.items():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (int, float, bool)):
                    parts.append(f"{key}:{value}")
        elif event.data is not None:
            parts.append(str(event.data))

        return " ".join([part for part in parts if part]).strip()

    def _cache_l4_event(self, event: Event, event_id: str) -> None:
        payload = {
            "id": event_id,
            "type": event.type,
            "data": event.data if isinstance(event.data, dict) else {"value": event.data},
            "timestamp": event.timestamp,
            "source": event.source,
            "level": event.level.value if hasattr(event.level, "value") else int(event.level),
            "correlation_id": event.correlation_id,
            "metadata": event.metadata,
        }
        self.unified_memory.l4_summaries.add_event(payload)

    async def _summary_generator(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.config.summary_interval_minutes * 60)
            except asyncio.CancelledError:
                break

            try:
                await self.generate_pending_summaries()
            except Exception as exc:
                logger.warning("Failed periodic summary generation: %s", exc)

    def _handle_l5_capability(self, event: Event) -> None:
        if event.type == EventTypes.TASK_COMPLETED:
            self._record_task_capability(event)
            self._stats["l5_capabilities_extracted"] += 1
            return

        if event.type == EventTypes.ACTION_EXECUTED:
            self._record_action_attempt(event)

    def _record_task_capability(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        self.unified_memory.l5_capabilities.record_attempt(
            task_id=str(data.get("task_id", "unknown")),
            context=event.metadata or {},
            action=data.get("action", {}),
            success=bool(data.get("success", True)),
            duration=float(data.get("duration", 0.0)),
            error=data.get("error"),
        )

    def _record_action_attempt(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        action_type = str(data.get("action_type", ""))
        if not action_type:
            return

        self.unified_memory.l5_capabilities.record_attempt(
            task_id=f"action_{action_type}",
            context={"event_type": event.type, "action_type": action_type},
            action={"type": action_type, "params": data.get("params", {})},
            success=bool(data.get("success", True)),
            duration=float(data.get("execution_time", 0.0)),
            error=data.get("error"),
        )

    async def _persist_all(self) -> None:
        if self.config.enable_l2_relations:
            self.unified_memory.l2_relations._save_to_disk()

        if self.config.enable_l3_embeddings and self.unified_memory.l3_embeddings:
            self.unified_memory.l3_embeddings._save_to_disk()

        if self.config.enable_l4_summaries and self.unified_memory.l4_summaries:
            self.unified_memory.l4_summaries._save_to_disk()

        if self.config.enable_l5_capabilities and self.unified_memory.l5_capabilities:
            self.unified_memory.l5_capabilities._save_to_disk()

    def get_statistics(self) -> Dict[str, Any]:
        queue_size = self._embedding_queue.qsize() if self._embedding_queue else 0
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
            "queue_size": queue_size,
        }

    async def generate_pending_summaries(self) -> None:
        if not self.config.enable_l4_summaries or not self.unified_memory.l4_summaries:
            return

        for period_type in ("hour", "day", "week", "month"):
            period_key = self.unified_memory.l4_summaries._get_period_key(time.time(), period_type)
            if period_key in self.unified_memory.l4_summaries._summaries.get(period_type, {}):
                continue

            summary = self.unified_memory.l4_summaries.generate_summary(period_type=period_type, period_key=period_key)
            if summary is not None:
                self._stats["l4_summaries_generated"] += 1


__all__ = [
    "MemoryIntegrationConfig",
    "MemoryIntegrationModule",
]
