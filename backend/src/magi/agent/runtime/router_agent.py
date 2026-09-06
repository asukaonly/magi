"""RouterAgent: infinite loop dispatcher for source events."""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import Optional

from ...awareness.source_hub import SourceHub
from ...core.logger import get_logger
from .contracts import FactRecord
from .task_agent_manager import TaskAgentManager
from .types import build_task_agent_key, get_task_agent_type_value

logger = get_logger(__name__)


@dataclass
class RouterAgentStats:
    batches: int = 0
    events: int = 0
    facts_written: int = 0
    facts_rejected: int = 0
    loop_crash_count: int = 0
    event_error_count: int = 0
    last_error: str | None = None
    last_restart_at: float | None = None


class RouterAgent:
    """Continuously pulls source batches and dispatches facts to runtime agents."""

    def __init__(
        self,
        source_hub: SourceHub,
        task_agent_manager: TaskAgentManager,
        batch_size: int = 16,
        poll_timeout_seconds: float = 0.2,
        restart_backoff_seconds: float = 1.0,
    ) -> None:
        self._source_hub = source_hub
        self._task_agent_manager = task_agent_manager
        self._batch_size = batch_size
        self._poll_timeout_seconds = poll_timeout_seconds
        self._restart_backoff_seconds = restart_backoff_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._supervisor_task: Optional[asyncio.Task] = None
        self._stats = RouterAgentStats()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self._supervisor_task = asyncio.create_task(self._supervisor())
        logger.info("RouterAgent started")

    async def stop(self) -> None:
        self._running = False
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
            self._supervisor_task = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("RouterAgent stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                batch = await self._source_hub.get_batch(
                    max_items=self._batch_size,
                    timeout_seconds=self._poll_timeout_seconds,
                )
                if not batch:
                    continue
                self._stats.batches += 1
                self._stats.events += len(batch)

                for source_event in batch:
                    try:
                        targets = self._task_agent_manager.resolve_targets(source_event)
                        for target_type, target_id in targets:
                            fact = FactRecord(
                                agent_id=build_task_agent_key(target_type, target_id),
                                agent_type=get_task_agent_type_value(target_type),
                                agent_instance_id=target_id,
                                event_type=source_event.event_type,
                                payload=source_event.payload,
                                timestamp=source_event.timestamp,
                                correlation_id=source_event.correlation_id,
                                user_message_generation=source_event.user_message_generation,
                                delivery_attempt_no=source_event.delivery_attempt_no,
                                runtime_command_id=source_event.runtime_command_id,
                            )
                            success = await self._task_agent_manager.add_fact_to_agent(target_type, target_id, fact)
                            if success:
                                self._stats.facts_written += 1
                            else:
                                self._stats.facts_rejected += 1
                    except Exception as event_exc:
                        self._stats.event_error_count += 1
                        self._stats.last_error = str(event_exc)
                        logger.error(
                            f"RouterAgent event processing failed | error={event_exc}",
                            exc_info=True,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as loop_exc:
                self._stats.last_error = str(loop_exc)
                logger.error(
                    f"RouterAgent loop iteration failed | error={loop_exc}",
                    exc_info=True,
                )
                raise

    async def _supervisor(self) -> None:
        while self._running:
            try:
                if self._task is None or self._task.done():
                    if self._task is not None:
                        try:
                            exc = self._task.exception()
                            if exc:
                                self._stats.loop_crash_count += 1
                                self._stats.last_restart_at = time.time()
                                logger.error(f"RouterAgent loop crashed, restarting | error={exc}")
                        except asyncio.CancelledError:
                            pass
                        except asyncio.InvalidStateError:
                            pass
                    if self._running:
                        await asyncio.sleep(self._restart_backoff_seconds)
                        self._task = asyncio.create_task(self._loop())
                        logger.info("RouterAgent loop restarted")
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"RouterAgent supervisor error | error={exc}")
                await asyncio.sleep(self._restart_backoff_seconds)

    def get_stats(self) -> dict:
        return asdict(self._stats)
