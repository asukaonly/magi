"""BatchDriver — production wiring: drive batch jobs via the real BackgroundManager.

Turns the engine's injected seams (``enqueue_run`` / ``on_batch_run_done``) into
real bounded background agent runs. ``on_terminal`` is registered as a
``BackgroundTaskManager`` terminal listener at bootstrap; ``kickoff`` is called by
``batch_create`` to fire the first batch. task-agnostic — it only reads
``job.handler_ref`` / ``job.handler_config`` and the opaque item inputs.

The manager is injected (not imported) so this stays unit-testable with a fake.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from magi_plugin_sdk.run_trigger import RunTrigger

from ..background import BackgroundTaskSpec, BackgroundTaskTriggerSource
from .contracts import BatchJobStatus
from .runner import (
    build_batch_goal,
    fill_to_concurrency,
    on_batch_run_done,
    parse_job_id_from_goal,
    parse_lease_owner_from_goal,
)
from .store import default_batch_store
from .tool_selection import (
    BatchToolRegistry,
    BatchToolSelectionError,
    resolve_batch_tool_names,
)

logger = logging.getLogger(__name__)


class BatchDriver:
    """Wraps the runtime BackgroundTaskManager to drive manifest batch jobs."""

    def __init__(
        self,
        manager: Any,
        *,
        tool_registry: BatchToolRegistry,
        store_factory: Any = default_batch_store,
    ) -> None:
        self._manager = manager
        self._tool_registry = tool_registry
        self._store_factory = store_factory

    async def _enqueue_run(self, job: Any, items: Any, *, tools: list[str]) -> None:
        prompt = job.handler_config.get("prompt") or f"Use skill '{job.handler_ref}' to process each item."
        spec = BackgroundTaskSpec(
            user_id=job.owner,
            session_id=job.origin_session_id,
            origin_turn_id=job.origin_turn_id,
            title=f"[batch:{job.job_id}] {job.title}",
            goal=build_batch_goal(prompt, job, items),
            selected_tools=tools,
            trigger_source=BackgroundTaskTriggerSource.RULE,
            trigger=RunTrigger(
                trigger_type="batch",
                source_channel="batch",
                requester=job.owner,
                priority="background",
                correlation=[job.job_id],
                payload={},
            ),
        )
        await self._manager.enqueue(spec)

    async def _admit_job(self, store: Any, job: Any) -> list[str]:
        try:
            return resolve_batch_tool_names(
                job.handler_config.get("tools"),
                registry=self._tool_registry,
            )
        except BatchToolSelectionError as exc:
            await store.set_job_status(job.job_id, BatchJobStatus.FAILED)
            logger.error(
                "Batch job rejected because its tool selection is unavailable | "
                "job_id=%s | error=%s",
                job.job_id,
                exc,
            )
            raise

    def _enqueue_admitted(
        self,
        tools: list[str],
    ) -> Callable[[Any, Any], Awaitable[None]]:
        async def enqueue(job: Any, items: Any) -> None:
            await self._enqueue_run(job, items, tools=tools)

        return enqueue

    def _effective_n(self, job: Any) -> int:
        """Batch's in-flight cap: honor job.concurrency, never exceed the global
        pool minus one reserved slot, but always allow at least 1."""
        return max(1, min(job.concurrency, self._manager.max_concurrent - 1))

    async def kickoff(self, job_id: str) -> int:
        """Lease + enqueue up to effective_N runs. Returns #runs started."""
        store = self._store_factory()
        job = await store.get_job(job_id)
        if job is None:
            return 0
        tools = await self._admit_job(store, job)
        return await fill_to_concurrency(
            store,
            job,
            enqueue_run=self._enqueue_admitted(tools),
            target_n=self._effective_n(job),
        )

    async def resume_running_jobs(self) -> int:
        """Restart recovery — STARTUP-ONLY (assumes no batch runs are in-flight).
        After a restart every 'running' item is an orphan (its run died with the
        process), so force-requeue all of them to pending — without waiting for
        the lease TTL — then refill to effective_N. Must NOT be called while runs
        are live, or it would re-drive items that are still being processed.
        Returns #jobs resumed."""
        store = self._store_factory()
        jobs = await store.list_jobs_by_status(BatchJobStatus.RUNNING)
        resumed = 0
        for job in jobs:
            try:
                tools = await self._admit_job(store, job)
            except BatchToolSelectionError:
                continue
            await store.requeue_running(job.job_id)
            await fill_to_concurrency(
                store,
                job,
                enqueue_run=self._enqueue_admitted(tools),
                target_n=self._effective_n(job),
            )
            resumed += 1
        return resumed

    async def on_terminal(self, task: Any) -> None:
        """BackgroundManager terminal listener: continue the chain or finalize."""
        goal = getattr(getattr(task, "spec", None), "goal", "") or ""
        job_id = parse_job_id_from_goal(goal)
        if job_id:
            store = self._store_factory()
            job = await store.get_job(job_id)
            if job is None:
                return
            try:
                tools = await self._admit_job(store, job)
            except BatchToolSelectionError:
                return
            await on_batch_run_done(
                store,
                job_id,
                enqueue_run=self._enqueue_admitted(tools),
                lease_owner=parse_lease_owner_from_goal(goal),
            )
