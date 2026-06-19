"""Async embedding worker helpers for L1 event embeddings."""

from __future__ import annotations

import asyncio
import time
from typing import cast

from ...event_contracts import MemoryEvent
from .common import L1EventEmbeddingHostProtocol


class L1EventEmbeddingWorkerMixin:
    """Own L1 embedding scheduling and async batch worker behavior."""

    async def _schedule_event_embedding(self, event: MemoryEvent) -> None:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if not host._vectors_enabled():
            return
        queue = host._embedding_queue
        if queue is not None and host._async_embeddings_enabled():
            await queue.put(event)
            return
        await host._maybe_upsert_event_embedding(event)

    async def _run_embedding_worker(self) -> None:
        host = cast(L1EventEmbeddingHostProtocol, self)
        queue = host._embedding_queue
        if queue is None:
            return
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break
            batch = [item]
            should_stop = False
            batch_size = max(1, int(host._embedding_batch_size))
            deadline = time.monotonic() + max(0.0, float(host._embedding_batch_wait_seconds))
            while len(batch) < batch_size:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if next_item is None:
                    queue.task_done()
                    should_stop = True
                    break
                batch.append(next_item)
            host._embedding_active_count += len(batch)
            try:
                await host._maybe_upsert_event_embeddings(batch)
            finally:
                host._embedding_active_count = max(
                    0,
                    host._embedding_active_count - len(batch),
                )
                for _ in batch:
                    queue.task_done()
            if should_stop:
                break
