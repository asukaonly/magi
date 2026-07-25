"""Lifecycle helpers for the unified memory store."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .shared_clear import clear_shared_auxiliary_memory

logger = logging.getLogger(__name__)

_MEMORY_ARCHIVE_FILE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}\.db(?:-wal|-shm)?$"
)


class MemoryClearCompletedWithRecoveryError(RuntimeError):
    """Report operational recovery failure after all clear steps committed."""

    def __init__(
        self,
        *,
        counts: dict[str, int],
        recovery_error: BaseException,
    ) -> None:
        super().__init__(str(recovery_error))
        self.counts = dict(counts)
        self.recovery_error = recovery_error


class UnifiedMemoryLifecycleMixin:
    """Initialize and shut down enabled L0-L4 stores."""

    memory_db_path: str
    l0: Any
    l1: Any
    l2: Any
    l2_entity_catalog: Any
    l2_pipeline: Any
    l3: Any
    l4: Any
    _edge_embedding_drainer: Any
    _edge_embedding_worker: Any
    _portrait_projection_scheduler: Any
    _archive_dir: Path
    _write_lock: Any
    _clear_barrier: Any
    _clear_epoch: int
    _initialized: bool

    async def initialize(self) -> None:
        """Initialize enabled stores."""
        if self._initialized:
            return

        for store in (self.l0, self.l1, self.l2, self.l2_entity_catalog, self.l3, self.l4):
            if store is None:
                continue
            await store.initialize()
        recovery = await self.resume_pending_forget_operations(
            force=True,
            fail_on_barrier_error=True,
        )
        if recovery["found"]:
            logger.info(
                "Recovered durable forget operations before memory writers started: %s",
                recovery,
            )
        if self.l2_pipeline is not None:
            await self.l2_pipeline.start()

        # Start the L2 edge-embedding drain only when vectors are enabled.
        if (
            self._edge_embedding_worker is not None
            and self.l2_entity_catalog is not None
            and self.l2_entity_catalog.embedding_service is not None
        ):
            await self._edge_embedding_worker.start()

        self._initialized = True
        logger.info("Unified memory store initialized")

    async def shutdown(self) -> None:
        """Drain asynchronous workers and close store resources."""
        if self.l2_pipeline is not None:
            await self.l2_pipeline.shutdown()
        if self._portrait_projection_scheduler is not None:
            await self._portrait_projection_scheduler.shutdown()
        if self._edge_embedding_worker is not None:
            await self._edge_embedding_worker.stop()
        for store in (self.l0, self.l1, self.l3, self.l4):
            if store is None or not hasattr(store, "shutdown"):
                continue
            await store.shutdown()

    async def clear_all_memory(
        self,
        *,
        auxiliary_clearers: Iterable[Callable[[], Any]] = (),
        context_clearer: Callable[[], Any] | None = None,
    ) -> dict[str, int]:
        """Quiesce background writers, clear every layer, and resume the runtime."""
        context_count = 0
        async with self._clear_barrier.exclusive():
            self._clear_epoch += 1
            async with self._write_lock:
                pipeline_was_running = bool(
                    self.l2_pipeline is not None
                    and getattr(getattr(self.l2_pipeline, "_stats", None), "is_running", False)
                )
                edge_worker_was_running = bool(
                    self._edge_embedding_worker is not None
                    and getattr(self._edge_embedding_worker, "_running", False)
                )
                l3_embedding_was_running = self._embedding_worker_is_running(self.l3)
                l4_embedding_was_running = self._embedding_worker_is_running(self.l4)
                l1_embedding_was_running = bool(
                    self.l1 is not None
                    and getattr(self.l1, "_embedding_workers", None)
                )
                clear_failure: BaseException | None = None
                clear_traceback = None
                try:
                    await self._quiesce_memory_writers()
                    l2_count = await self.l2.clear() if self.l2 is not None else 0
                    if self.l2_entity_catalog is not None:
                        l2_count += await self.l2_entity_catalog.clear()
                    if self.l2_pipeline is not None:
                        await self.l2_pipeline.reset_after_clear()
                    await clear_shared_auxiliary_memory(self.memory_db_path)
                    l0_count = await self.l0.clear() if self.l0 is not None else 0
                    l1_count = (
                        await self.l1.clear(restart_workers=False)
                        if self.l1 is not None
                        else 0
                    )
                    l3_count = await self.l3.clear() if self.l3 is not None else 0
                    l4_count = await self.l4.clear() if self.l4 is not None else 0
                    self._clear_archived_memory_files()
                    await self._run_auxiliary_clearers(auxiliary_clearers)
                    if context_clearer is not None:
                        context_result = await self._run_clearer(context_clearer)
                        context_count = int(context_result or 0)
                except BaseException as exc:
                    clear_failure = exc
                    clear_traceback = exc.__traceback__

                resume_failure: BaseException | None = None
                try:
                    await self._resume_memory_writers(
                        pipeline_was_running=pipeline_was_running,
                        edge_worker_was_running=edge_worker_was_running,
                        l1_embedding_was_running=l1_embedding_was_running,
                        l3_embedding_was_running=l3_embedding_was_running,
                        l4_embedding_was_running=l4_embedding_was_running,
                    )
                except BaseException as exc:
                    resume_failure = exc

                if clear_failure is not None:
                    if resume_failure is not None:
                        logger.error(
                            "Failed to resume memory writers after clear failure",
                            exc_info=(
                                type(resume_failure),
                                resume_failure,
                                resume_failure.__traceback__,
                            ),
                        )
                    raise clear_failure.with_traceback(clear_traceback)
                if resume_failure is not None:
                    raise MemoryClearCompletedWithRecoveryError(
                        counts={
                            "l0": l0_count,
                            "l1": l1_count,
                            "l2": l2_count,
                            "l3": l3_count,
                            "l4": l4_count,
                            "chat_context": context_count,
                        },
                        recovery_error=resume_failure,
                    ) from resume_failure
        return {
            "l0": l0_count,
            "l1": l1_count,
            "l2": l2_count,
            "l3": l3_count,
            "l4": l4_count,
            "chat_context": context_count,
        }

    def memory_operation_guard(self) -> Any:
        """Return a shared guard for scheduler and API memory operations."""
        return self._clear_barrier.operation()

    def memory_operation_epoch(self) -> int:
        """Return the process-local epoch used to reject pre-clear queued work."""
        return int(self._clear_epoch)

    async def _quiesce_memory_writers(self) -> None:
        if self.l2_pipeline is not None:
            await self.l2_pipeline.abort_for_clear()
        if self._portrait_projection_scheduler is not None:
            await self._portrait_projection_scheduler.shutdown()
        if self._edge_embedding_worker is not None:
            await self._edge_embedding_worker.stop()
        for store in (self.l1, self.l3, self.l4):
            if store is not None and hasattr(store, "abort_for_clear"):
                await store.abort_for_clear()

    async def _resume_memory_writers(
        self,
        *,
        pipeline_was_running: bool,
        edge_worker_was_running: bool,
        l1_embedding_was_running: bool,
        l3_embedding_was_running: bool,
        l4_embedding_was_running: bool,
    ) -> None:
        operations: list[tuple[str, Callable[[], Any]]] = []
        if l4_embedding_was_running and self.l4 is not None:
            operations.append(("l4_embedding", self.l4.initialize))
        if l3_embedding_was_running and self.l3 is not None:
            operations.append(("l3_embedding", self.l3.initialize))
        if l1_embedding_was_running and self.l1 is not None:
            operations.append(("l1_embedding", self.l1.initialize))
        if edge_worker_was_running and self._edge_embedding_worker is not None:
            operations.append(("l2_edge_embedding", self._edge_embedding_worker.start))
        if pipeline_was_running and self.l2_pipeline is not None:
            operations.append(("l2_pipeline", self.l2_pipeline.start))
        failures: list[tuple[str, Exception]] = []
        for name, operation in operations:
            try:
                await operation()
            except Exception as exc:
                logger.exception("Failed to resume memory writer: %s", name)
                failures.append((name, exc))
        if failures:
            failed_names = ", ".join(name for name, _ in failures)
            raise RuntimeError(
                f"Failed to resume memory writers after clear: {failed_names}"
            ) from failures[0][1]

    @staticmethod
    def _embedding_worker_is_running(store: Any) -> bool:
        worker = getattr(store, "_embedding_worker", None)
        return bool(worker is not None and not worker.done())

    def _clear_archived_memory_files(self) -> None:
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        for path in self._archive_dir.iterdir():
            if path.is_file() and _MEMORY_ARCHIVE_FILE_PATTERN.fullmatch(path.name):
                path.unlink()

    @staticmethod
    async def _run_auxiliary_clearers(
        clearers: Iterable[Callable[[], Any]],
    ) -> None:
        for clearer in clearers:
            await UnifiedMemoryLifecycleMixin._run_clearer(clearer)

    @staticmethod
    async def _run_clearer(clearer: Callable[[], Any]) -> Any:
        if inspect.iscoroutinefunction(clearer):
            return await clearer()
        result = await asyncio.to_thread(clearer)
        if inspect.isawaitable(result):
            return await result
        return result


__all__ = ["UnifiedMemoryLifecycleMixin"]
