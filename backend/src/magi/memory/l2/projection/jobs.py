"""Projection job queue facade for the L2 cognition store."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Dict

from ..batch_models import L2ProjectionLease
from .queue import ProjectionJobQueue


class L2ProjectionJobStoreMixin:
    """Expose L2 projection queue operations through the store API."""

    _projection_queue: ProjectionJobQueue

    async def initialize(self) -> None:
        raise NotImplementedError

    async def enqueue_projection_job(
        self,
        *,
        event_id: str,
        source: str,
        event_type: str,
        batch_owner: str | None = None,
        catch_up_owner: str | None = None,
        max_events: int | None = None,
        min_ready_events: int | None = None,
        max_wait_seconds: float | None = None,
    ) -> bool:
        """Insert one pending L2 projection job if it does not already exist."""
        await self.initialize()
        return await self._projection_queue.enqueue(
            event_id=event_id,
            source=source,
            event_type=event_type,
            batch_owner=batch_owner,
            catch_up_owner=catch_up_owner,
            max_events=max_events,
            min_ready_events=min_ready_events,
            max_wait_seconds=max_wait_seconds,
        )

    async def has_projection_job(self, *, event_id: str) -> bool:
        """Return whether an L1 event has reached the durable L2 queue."""
        await self.initialize()
        return await self._projection_queue.has_job(event_id=event_id)

    async def claim_ready_projection_jobs(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim pending jobs whose owner bucket is ready for extraction."""
        await self.initialize()
        return await self._projection_queue.claim_ready(
            consumer_name=consumer_name,
            limit=limit,
        )

    async def claim_projection_jobs(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim up to *limit* pending projection jobs ordered by creation time."""
        await self.initialize()
        return await self._projection_queue.claim(
            consumer_name=consumer_name,
            limit=limit,
        )

    async def mark_projection_jobs_running(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        consumer_name: str,
    ) -> int:
        """Mark queued projection jobs as actively running."""
        normalized = tuple(leases)
        if not normalized:
            return 0
        await self.initialize()
        return await self._projection_queue.mark_running(
            leases=normalized,
            consumer_name=consumer_name,
        )

    async def complete_projection_jobs(self, leases: Iterable[L2ProjectionLease]) -> int:
        """Complete only projection attempts that still own their leases."""
        normalized = tuple(leases)
        if not normalized:
            return 0
        await self.initialize()
        return await self._projection_queue.complete(leases=normalized)

    async def touch_running_projection_jobs(
        self,
        leases: Iterable[L2ProjectionLease],
    ) -> int:
        """Refresh a running projection lease set before a persistence boundary."""

        normalized = tuple(leases)
        if not normalized:
            return 0
        await self.initialize()
        return await self._projection_queue.touch_running(leases=normalized)

    async def fail_projection_jobs(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        error_text: str | None = None,
        requeue: bool,
    ) -> int:
        """Mark projection jobs as failed or return them to pending."""
        normalized = tuple(leases)
        if not normalized:
            return 0
        await self.initialize()
        return await self._projection_queue.fail(
            leases=normalized,
            error_text=error_text,
            requeue=requeue,
        )

    async def requeue_stale_projection_jobs(
        self,
        *,
        queued_timeout_seconds: float,
        running_timeout_seconds: float,
    ) -> int:
        """Return stale queued or running jobs back to pending for replay."""
        await self.initialize()
        return await self._projection_queue.requeue_stale(
            queued_timeout_seconds=queued_timeout_seconds,
            running_timeout_seconds=running_timeout_seconds,
        )

    async def get_projection_backlog_stats(
        self,
        *,
        source_filter: str | None = None,
    ) -> Dict[str, int]:
        """Return counts for durable L2 projection jobs by status."""
        await self.initialize()
        return await self._projection_queue.get_backlog_stats(source_filter=source_filter)
