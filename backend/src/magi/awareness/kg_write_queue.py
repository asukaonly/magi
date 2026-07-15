"""Bounded batch writer for sensor-derived knowledge graph edges."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class KnowledgeGraphEdgeWrite:
    """Normalized edge write request for the user knowledge graph."""

    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    fact_kind: str | None
    evidence_event_ids: tuple[str, ...]
    confidence: float
    observed_at: float
    source_type: str
    subject_attributes: Mapping[str, Any]
    object_attributes: Mapping[str, Any]

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "predicate": self.predicate,
            "object_id": self.object_id,
            "object_type": self.object_type,
            "fact_kind": self.fact_kind,
            "evidence_event_ids": list(self.evidence_event_ids),
            "confidence": self.confidence,
            "observed_at": self.observed_at,
            "source_type": self.source_type,
            "subject_attributes": dict(self.subject_attributes),
            "object_attributes": dict(self.object_attributes),
        }


@dataclass(frozen=True, slots=True)
class KnowledgeGraphWriteQueueStats:
    queue_length: int
    max_queue_size: int
    max_batch_size: int
    running: bool
    enqueued_count: int
    flushed_batch_count: int
    flushed_edge_count: int
    retry_count: int
    failed_batch_count: int
    last_flush_latency_ms: float | None


_STOP = object()


@dataclass(frozen=True, slots=True)
class _QueuedKnowledgeGraphEdgeWrite:
    edge: KnowledgeGraphEdgeWrite
    expected_epoch: int


class KnowledgeGraphWriteQueue:
    """Serialize and batch high-volume graph edge writes from sensor events."""

    def __init__(
        self,
        *,
        unified_memory,
        max_queue_size: int = 10000,
        max_batch_size: int = 100,
        flush_interval_seconds: float = 0.25,
        retry_attempts: int = 2,
    ) -> None:
        self._memory = unified_memory
        self._max_batch_size = max(1, int(max_batch_size))
        self._flush_interval_seconds = max(0.001, float(flush_interval_seconds))
        self._retry_attempts = max(0, int(retry_attempts))
        self._queue: asyncio.Queue[_QueuedKnowledgeGraphEdgeWrite | object] = asyncio.Queue(
            maxsize=max(1, int(max_queue_size))
        )
        self._worker_task: asyncio.Task | None = None
        self._enqueued_count = 0
        self._flushed_batch_count = 0
        self._flushed_edge_count = 0
        self._retry_count = 0
        self._failed_batch_count = 0
        self._last_flush_latency_ms: float | None = None

    async def start(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="knowledge-graph-write-queue")

    async def stop(self) -> None:
        task = self._worker_task
        if task is None:
            return
        if task.done():
            await task
            self._worker_task = None
            return
        await self.drain()
        await self._queue.put(_STOP)
        await self._queue.join()
        await task
        self._worker_task = None

    async def drain(self) -> None:
        task = self._worker_task
        if task is None:
            return
        if task.done():
            await task
            return
        await self._queue.join()

    async def add_edge(self, edge: KnowledgeGraphEdgeWrite) -> None:
        if self._worker_task is None or self._worker_task.done():
            raise RuntimeError("KnowledgeGraphWriteQueue is not running")
        await self._queue.put(
            _QueuedKnowledgeGraphEdgeWrite(
                edge=edge,
                expected_epoch=int(self._memory.memory_operation_epoch()),
            )
        )
        self._enqueued_count += 1

    def get_stats(self) -> KnowledgeGraphWriteQueueStats:
        task = self._worker_task
        return KnowledgeGraphWriteQueueStats(
            queue_length=self._queue.qsize(),
            max_queue_size=self._queue.maxsize,
            max_batch_size=self._max_batch_size,
            running=task is not None and not task.done(),
            enqueued_count=self._enqueued_count,
            flushed_batch_count=self._flushed_batch_count,
            flushed_edge_count=self._flushed_edge_count,
            retry_count=self._retry_count,
            failed_batch_count=self._failed_batch_count,
            last_flush_latency_ms=self._last_flush_latency_ms,
        )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is _STOP:
                self._queue.task_done()
                return

            batch = [item]
            should_stop = False
            deadline = asyncio.get_running_loop().time() + self._flush_interval_seconds

            while len(batch) < self._max_batch_size:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if next_item is _STOP:
                    self._queue.task_done()
                    should_stop = True
                    break
                batch.append(next_item)

            try:
                await self._flush_batch(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

            if should_stop:
                return

    async def _flush_batch(
        self,
        batch: list[_QueuedKnowledgeGraphEdgeWrite | object],
    ) -> None:
        grouped: dict[int, list[KnowledgeGraphEdgeWrite]] = {}
        for item in batch:
            if isinstance(item, _QueuedKnowledgeGraphEdgeWrite):
                grouped.setdefault(item.expected_epoch, []).append(item.edge)
        for expected_epoch, edges in grouped.items():
            await self._flush_epoch_batch(edges, expected_epoch=expected_epoch)

    async def _flush_epoch_batch(
        self,
        edges: list[KnowledgeGraphEdgeWrite],
        *,
        expected_epoch: int,
    ) -> None:

        for attempt in range(self._retry_attempts + 1):
            started_at = time.perf_counter()
            try:
                accepted_count = await self._write_edges(
                    edges,
                    expected_epoch=expected_epoch,
                )
                self._last_flush_latency_ms = (time.perf_counter() - started_at) * 1000.0
                if accepted_count > 0:
                    self._flushed_batch_count += 1
                    self._flushed_edge_count += accepted_count
                return
            except Exception:
                if attempt >= self._retry_attempts:
                    self._failed_batch_count += 1
                    logger.exception(
                        "knowledge_graph edge batch failed (edges=%s)",
                        len(edges),
                    )
                    return
                self._retry_count += 1
                logger.warning(
                    "knowledge_graph edge batch retrying (attempt=%s)",
                    attempt + 1,
                    exc_info=True,
                )
                await asyncio.sleep(min(1.0, 0.05 * (2**attempt)))

    async def _write_edges(
        self,
        edges: list[KnowledgeGraphEdgeWrite],
        *,
        expected_epoch: int,
    ) -> int:
        batch_writer = getattr(self._memory, "upsert_user_graph_edges", None)
        if callable(batch_writer):
            result = batch_writer(
                [edge.to_kwargs() for edge in edges],
                expected_epoch=expected_epoch,
            )
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, (list, tuple, set)):
                return len(result)
            return int(bool(result))

        accepted_count = 0
        for edge in edges:
            result = self._memory.upsert_user_graph_edge(
                **edge.to_kwargs(),
                expected_epoch=expected_epoch,
            )
            if inspect.isawaitable(result):
                result = await result
            accepted_count += int(bool(result))
        return accepted_count
