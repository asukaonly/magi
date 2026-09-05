"""Memory integration pipeline for routing runtime events into durable memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..core.logger import get_logger
from ..events.backend import MessageBusBackend
from ..events.events import Event, EventTypes, published_memory_epoch
from . import UnifiedMemoryStore
from .event_contracts import IngestTarget

logger = get_logger(__name__)

MEMORY_DIAGNOSTIC_EVENT_TYPES: Set[str] = {
    EventTypes.ACTION_EXECUTED,
}


@dataclass
class MemoryIntegrationConfig:
    """Configuration for MemoryIntegrationModule."""

    enable_l1: bool = True
    enable_l2: bool = True
    enable_l3: bool = True
    enable_l4: bool = True

    subscribed_events: Set[str] = field(
        default_factory=lambda: {
            EventTypes.ACTION_EXECUTED,
            EventTypes.TASK_COMPLETED,
            EventTypes.TASK_FAILED,
            EventTypes.ERROR_OCCURRED,
            EventTypes.LOOP_STARTED,
            EventTypes.LOOP_PHASE_STARTED,
        }
    )


@dataclass
class MemoryIntegrationStats:
    """Fixed counters for memory integration activity."""

    events_received: int = 0
    events_processed: int = 0
    events_failed: int = 0
    l1_stored: int = 0
    l1_filtered: int = 0
    l2_relations_written: int = 0
    l2_assertions_written: int = 0
    l2_extract_enqueued: int = 0
    l2_extract_completed: int = 0
    l2_extract_failed: int = 0
    l2_extract_skipped: int = 0
    l3_summaries_generated: int = 0
    l4_skills_updated: int = 0


class MemoryIntegrationModule:
    """Bridges message bus events into the unified memory layers."""

    def __init__(
        self,
        unified_memory: UnifiedMemoryStore,
        message_bus: MessageBusBackend,
        config: Optional[MemoryIntegrationConfig] = None,
    ) -> None:
        self.unified_memory = unified_memory
        self.message_bus = message_bus
        self.config = config or MemoryIntegrationConfig()

        self._running = False
        self._subscription_ids: List[str] = []
        self._stats = MemoryIntegrationStats()

    async def start(self) -> None:
        """Subscribe to runtime events and start maintenance tasks."""
        if self._running:
            return

        self._running = True
        await self._subscribe_to_events()
        logger.info("MemoryIntegrationModule started")

    async def stop(self) -> None:
        """Stop subscriptions and checkpoint the working memory."""
        if not self._running:
            return

        self._running = False
        await self._unsubscribe_from_events()

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
        self._stats.events_received += 1
        expected_epoch = published_memory_epoch(event)
        if expected_epoch is None:
            self._stats.events_failed += 1
            logger.error(
                "MemoryIntegration rejected event without a valid publication epoch | "
                "type=%s correlation_id=%s source=%s",
                event.type,
                event.correlation_id,
                event.source,
            )
            return
        if event.type in MEMORY_DIAGNOSTIC_EVENT_TYPES:
            payload = event.data if isinstance(event.data, dict) else {}
            logger.info(
                "MemoryIntegration received event | type=%s correlation_id=%s session_id=%s user_id=%s turn_id=%s source=%s",
                event.type,
                event.correlation_id,
                payload.get("session_id"),
                payload.get("user_id"),
                payload.get("turn_id"),
                event.source,
            )
        try:
            result = await self.unified_memory.ingest_event(
                event,
                expected_epoch=expected_epoch,
            )
            if event.type in MEMORY_DIAGNOSTIC_EVENT_TYPES:
                logger.info(
                    "MemoryIntegration ingested event | type=%s correlation_id=%s event_id=%s ingest_target=%s l1_written=%s",
                    event.type,
                    event.correlation_id,
                    result.get("event_id"),
                    result.get("ingest_target"),
                    result.get("l1_written"),
                )
            if result["l1_written"]:
                self._stats.l1_stored += 1
            else:
                self._stats.l1_filtered += 1
            self._stats.l2_relations_written += int(result["l2_relation_count"])
            self._stats.l2_assertions_written += int(result["l2_assertion_count"])
            if result["l4_skill_id"]:
                self._stats.l4_skills_updated += 1
            self._stats.events_processed += 1
        except Exception as exc:
            self._stats.events_failed += 1
            payload = event.data if isinstance(event.data, dict) else {}
            logger.exception(
                "Failed to process event %s: %s",
                event.type,
                exc,
                extra={
                    "correlation_id": event.correlation_id,
                    "session_id": payload.get("session_id"),
                    "user_id": payload.get("user_id"),
                    "turn_id": payload.get("turn_id"),
                    "source": event.source,
                },
            )

    async def _maybe_store_l1(self, event: Event) -> bool:
        """Test helper for the L1 routing decision."""
        normalized = self.unified_memory._normalize_event(event)
        if normalized.ingest_target == IngestTarget.RUNTIME_ONLY:
            self._stats.l1_filtered += 1
            return False
        result = await self.unified_memory.ingest_event(normalized)
        if result["l1_written"]:
            self._stats.l1_stored += 1
        return bool(result["l1_written"])

    async def generate_pending_summaries(self) -> None:
        """Force-generate an hourly summary on demand."""
        summary = await self.unified_memory.generate_summary(period_type="hour")
        if summary is not None:
            self._stats.l3_summaries_generated += 1

    async def _persist_all(self) -> None:
        if self.unified_memory.l0 is not None:
            await self.unified_memory.l0.checkpoint_all()

    def get_statistics(self) -> Dict[str, Any]:
        """Expose integration counters and active config."""
        stats = asdict(self._stats)
        pipeline_stats = self.unified_memory.get_l2_pipeline_stats()
        if pipeline_stats:
            stats["l2_extract_enqueued"] = int(pipeline_stats["extract_enqueued"])
            stats["l2_extract_completed"] = int(pipeline_stats["extract_completed"])
            stats["l2_extract_failed"] = int(pipeline_stats["extract_failed"])
            stats["l2_extract_skipped"] = int(pipeline_stats["extract_skipped"])
            stats["l2_relations_written"] = max(
                int(stats["l2_relations_written"]),
                int(pipeline_stats["relations_written"]),
            )
            stats["l2_assertions_written"] = max(
                int(stats["l2_assertions_written"]),
                int(pipeline_stats["assertions_written"]),
            )
        return {
            **stats,
            "config": {
                "enable_l1": self.config.enable_l1,
                "enable_l2": self.config.enable_l2,
                "enable_l3": self.config.enable_l3,
                "enable_l4": self.config.enable_l4,
            },
            "subscription_count": len(self._subscription_ids),
        }


__all__ = ["MemoryIntegrationConfig", "MemoryIntegrationModule"]
