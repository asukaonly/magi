"""Lifecycle helpers for the unified memory store."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import stat
from collections.abc import Callable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from magi_plugin_sdk.fs import (
    list_managed_directory_names,
    path_is_link,
    remove_managed_file,
)

from ..core.sqlite import secure_compact_sqlite
from .clear_generation import current_memory_clear_generation
from .l2.projection.entity_links import (
    begin_event_entity_link_projection_clear,
    clear_event_entity_link_projection_recovery,
)
from .shared_clear import clear_shared_auxiliary_memory

logger = logging.getLogger(__name__)

_MEMORY_ARCHIVE_FILE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.db(?:-wal|-shm|-journal)?$")


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
    l1_db_path: str
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
    _clear_request_count: int
    _post_turn_forget_operations: set[str]
    _initialized: bool

    async def initialize(
        self,
        *,
        start_workers: bool = True,
        recover_pending: bool = True,
        restore_runtime_state: bool = True,
    ) -> None:
        """Initialize enabled stores."""
        if self._initialized:
            return

        for store in (self.l0, self.l1, self.l2, self.l2_entity_catalog, self.l3, self.l4):
            if store is None:
                continue
            if store is self.l0:
                await store.initialize(restore_state=restore_runtime_state)
            elif store in (self.l1, self.l3, self.l4):
                await store.initialize(start_workers=start_workers)
            else:
                await store.initialize()
        if self.l1 is not None:
            await self.l1.align_entity_link_projection_clear_generation(
                await current_memory_clear_generation(self.memory_db_path)
            )
        if recover_pending:
            recovery = await self.resume_pending_forget_operations(
                force=True,
                fail_on_barrier_error=True,
            )
            if recovery["found"]:
                logger.info(
                    "Recovered durable forget operations before memory writers started: %s",
                    recovery,
                )
        if start_workers and self.l2_pipeline is not None:
            await self.l2_pipeline.start()

        # Start the L2 edge-embedding drain only when vectors are enabled.
        if (
            start_workers
            and self._edge_embedding_worker is not None
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
        user_content_clear_boundaries: Iterable[Callable[[], Any]] = (),
    ) -> dict[str, int]:
        """Quiesce background writers, clear every layer, and resume the runtime."""
        context_count = 0
        self._clear_request_count += 1
        try:
            async with self._clear_barrier.exclusive():
                self._clear_epoch += 1
                async with self._write_lock:
                    pipeline_was_running = bool(
                        self.l2_pipeline is not None
                        and getattr(
                            getattr(self.l2_pipeline, "_stats", None),
                            "is_running",
                            False,
                        )
                    )
                    edge_worker_was_running = bool(
                        self._edge_embedding_worker is not None
                        and getattr(self._edge_embedding_worker, "_running", False)
                    )
                    l3_embedding_was_running = self._embedding_worker_is_running(self.l3)
                    l4_embedding_was_running = self._embedding_worker_is_running(self.l4)
                    l1_embedding_was_running = bool(
                        self.l1 is not None and getattr(self.l1, "_embedding_workers", None)
                    )
                    clear_failure: BaseException | None = None
                    clear_traceback = None
                    try:
                        async with AsyncExitStack() as clear_boundary_stack:
                            for boundary in user_content_clear_boundaries:
                                await clear_boundary_stack.enter_async_context(boundary())
                            await self._quiesce_memory_writers()
                            entity_link_clear_generation = (
                                await begin_event_entity_link_projection_clear(
                                    self.memory_db_path
                                )
                            )
                            if self.l1 is not None:
                                l1_count = await self.l1.clear(
                                    restart_workers=False,
                                    entity_link_clear_generation=(
                                        entity_link_clear_generation
                                    ),
                                )
                            else:
                                l1_count = self._clear_dormant_l1_database()
                            if self.l2 is not None:
                                l2_count = await self.l2.clear(
                                    entity_link_clear_generation=(
                                        entity_link_clear_generation
                                    )
                                )
                            else:
                                l2_count = 0
                                await clear_event_entity_link_projection_recovery(
                                    self.memory_db_path,
                                    expected_clear_generation=(
                                        entity_link_clear_generation
                                    ),
                                )
                            if self.l2_entity_catalog is not None:
                                l2_count += await self.l2_entity_catalog.clear()
                            if self.l2_pipeline is not None:
                                await self.l2_pipeline.reset_after_clear()
                            l0_count = await self.l0.clear() if self.l0 is not None else 0
                            l3_count = await self.l3.clear() if self.l3 is not None else 0
                            l4_count = await self.l4.clear() if self.l4 is not None else 0
                            shared_counts = await clear_shared_auxiliary_memory(
                                self.memory_db_path,
                                advance_clear_generation=False,
                            )
                            l0_count += shared_counts.l0
                            l2_count += shared_counts.l2
                            l3_count += shared_counts.l3
                            l4_count += shared_counts.l4
                            self._clear_archived_memory_files()
                            await self._run_auxiliary_clearers(auxiliary_clearers)
                            if context_clearer is not None:
                                context_result = await self._run_clearer(context_clearer)
                                context_count = int(context_result or 0)
                            await secure_compact_sqlite(self.memory_db_path)
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
        finally:
            self._clear_request_count -= 1
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

    @asynccontextmanager
    async def memory_maintenance_guard(self) -> Any:
        """Quiesce memory writers and hold exclusive access for maintenance.

        Portability snapshots need one cross-database cut while L1-L4 writers
        and embedding workers are stopped. The maintenance window does not
        advance the destructive-clear epoch because no durable state changes.
        """

        self._clear_request_count += 1
        try:
            async with self._clear_barrier.exclusive():
                async with self._write_lock:
                    pipeline_was_running = bool(
                        self.l2_pipeline is not None
                        and getattr(getattr(self.l2_pipeline, "_stats", None), "is_running", False)
                    )
                    edge_worker_was_running = bool(
                        self._edge_embedding_worker is not None
                        and getattr(self._edge_embedding_worker, "_running", False)
                    )
                    l1_embedding_was_running = bool(
                        self.l1 is not None and getattr(self.l1, "_embedding_workers", None)
                    )
                    l3_embedding_was_running = self._embedding_worker_is_running(self.l3)
                    l4_embedding_was_running = self._embedding_worker_is_running(self.l4)
                    operation_error: BaseException | None = None
                    operation_traceback = None
                    try:
                        await self._quiesce_memory_writers()
                        yield
                    except BaseException as exc:
                        operation_error = exc
                        operation_traceback = exc.__traceback__
                    resume_error: BaseException | None = None
                    try:
                        await self._resume_memory_writers(
                            pipeline_was_running=pipeline_was_running,
                            edge_worker_was_running=edge_worker_was_running,
                            l1_embedding_was_running=l1_embedding_was_running,
                            l3_embedding_was_running=l3_embedding_was_running,
                            l4_embedding_was_running=l4_embedding_was_running,
                        )
                    except BaseException as exc:
                        resume_error = exc
                    if operation_error is not None:
                        if resume_error is not None:
                            logger.exception(
                                "Failed to resume memory writers after maintenance failure",
                                exc_info=(
                                    type(resume_error),
                                    resume_error,
                                    resume_error.__traceback__,
                                ),
                            )
                        raise operation_error.with_traceback(operation_traceback)
                    if resume_error is not None:
                        raise RuntimeError(
                            "Memory maintenance completed but writers could not resume"
                        ) from resume_error
        finally:
            self._clear_request_count -= 1

    def memory_operation_epoch(self) -> int:
        """Return the process-local epoch used to reject stale queued work."""
        return int(self._clear_epoch)

    def memory_clear_in_progress(self) -> bool:
        """Return whether a full clear is active or waiting for admission."""
        return self._clear_request_count > 0

    def _activate_post_turn_forget_epoch(self, operation_id: str) -> None:
        """Fence post-turn work admitted before one forget operation."""

        normalized = str(operation_id or "").strip()
        if not normalized or normalized in self._post_turn_forget_operations:
            return
        self._post_turn_forget_operations.add(normalized)
        self._clear_epoch += 1

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
        self._ensure_real_archive_directory()
        for name in list_managed_directory_names(self._archive_dir):
            if _MEMORY_ARCHIVE_FILE_PATTERN.fullmatch(name):
                remove_managed_file(self._archive_dir / name)

    def _clear_dormant_l1_database(self) -> int:
        """Remove a persisted L1 database even when L1 is disabled."""

        for suffix in ("", "-wal", "-shm", "-journal"):
            remove_managed_file(f"{self.l1_db_path}{suffix}")
        return 0

    def _ensure_real_archive_directory(self) -> None:
        """Replace an archive-directory link or file without entering its target."""

        try:
            archive_stat = os.lstat(self._archive_dir)
        except FileNotFoundError:
            archive_stat = None
        if archive_stat is not None:
            if path_is_link(self._archive_dir, path_stat=archive_stat) or not stat.S_ISDIR(
                archive_stat.st_mode
            ):
                remove_managed_file(self._archive_dir)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

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
