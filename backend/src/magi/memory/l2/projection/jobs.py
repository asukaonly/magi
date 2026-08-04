"""Projection job queue facade for the L2 cognition store."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Dict, Protocol, cast

import aiosqlite

from ..batch_models import L2ProjectionLease, derive_projection_attempt_key
from .models import TerminalClaimFailureContext
from .queue import (
    ProjectionCompletionCallback,
    ProjectionJobQueue,
    ProjectionTerminalCallback,
)


class _TerminalClaimFailureHostProtocol(Protocol):
    async def _append_terminal_claim_projection_failure_outcomes_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        context: TerminalClaimFailureContext,
        terminal_leases: tuple[L2ProjectionLease, ...],
    ) -> int: ...

    async def _finalize_event_entity_link_outbox_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        leases: tuple[L2ProjectionLease, ...],
    ) -> int: ...


def _terminal_claim_callback(
    host: _TerminalClaimFailureHostProtocol,
    context: TerminalClaimFailureContext,
) -> ProjectionTerminalCallback:
    async def callback(
        db: aiosqlite.Connection,
        terminal_leases: tuple[L2ProjectionLease, ...],
    ) -> None:
        effective_context = context
        if context.attempt_key is None and context.target_id is None:
            attempt_key = derive_projection_attempt_key(terminal_leases)
            target_id = (
                f"projection_event:{terminal_leases[0].event_id}"
                if len(terminal_leases) == 1
                else f"projection_attempt:{attempt_key}"
            )
            effective_context = TerminalClaimFailureContext(
                error_type=context.error_type,
                reason_code=context.reason_code,
                attempt_key=attempt_key,
                target_id=target_id,
            )
        await host._append_terminal_claim_projection_failure_outcomes_on_connection(
            db,
            context=effective_context,
            terminal_leases=terminal_leases,
        )

    return callback


def _entity_link_completion_callback(
    host: _TerminalClaimFailureHostProtocol,
) -> ProjectionCompletionCallback:
    async def callback(
        db: aiosqlite.Connection,
        leases: tuple[L2ProjectionLease, ...],
    ) -> None:
        await host._finalize_event_entity_link_outbox_on_connection(
            db,
            leases=leases,
        )

    return callback


class L2ProjectionJobStoreMixin:
    """Expose L2 projection queue operations through the store API."""

    _projection_queue: ProjectionJobQueue

    async def initialize(self) -> None:
        raise NotImplementedError

    def memory_correction_job_guard(self) -> Any:
        """Return the shared projection/correction persistence guard."""
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
        if int(limit) <= 0:
            return []
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
        if int(limit) <= 0:
            return []
        await self.initialize()
        return await self._projection_queue.claim(
            consumer_name=consumer_name,
            limit=limit,
        )

    async def request_projection_replay(self, event_id: str) -> bool:
        """Request a new durable attempt for an existing projection row."""

        if not str(event_id or "").strip():
            return False
        await self.initialize()
        return await self._projection_queue.request_replay(event_id=event_id)

    async def recover_foreign_projection_jobs(self, *, consumer_name: str) -> int:
        """Recover in-flight leases left by a previous backend process."""

        if not str(consumer_name or "").strip():
            return 0
        await self.initialize()
        host = cast(_TerminalClaimFailureHostProtocol, self)
        async with self.memory_correction_job_guard():
            return await self._projection_queue.recover_foreign_attempts(
                consumer_name=consumer_name,
                terminal_callback=_terminal_claim_callback(
                    host,
                    TerminalClaimFailureContext(
                        error_type="ProjectionAttemptRecoveredOnStartup",
                        reason_code="pipeline_retry_budget_exhausted_on_startup",
                    ),
                ),
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

    async def bind_projection_job_batch(
        self,
        leases: Iterable[L2ProjectionLease],
        *,
        consumer_name: str,
        attempt_key: str | None = None,
    ) -> int:
        """Bind queued rows to one exact final batch before worker dispatch."""

        normalized = tuple(leases)
        if not normalized:
            return 0
        await self.initialize()
        return await self._projection_queue.bind_queued_batch(
            leases=normalized,
            consumer_name=consumer_name,
            attempt_key=attempt_key,
        )

    async def complete_projection_jobs(self, leases: Iterable[L2ProjectionLease]) -> int:
        """Complete only projection attempts that still own their leases."""
        normalized = tuple(leases)
        if not normalized:
            return 0
        await self.initialize()
        host = cast(_TerminalClaimFailureHostProtocol, self)
        return await self._projection_queue.complete(
            leases=normalized,
            completion_callback=_entity_link_completion_callback(host),
        )

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
        terminal_claim_failure: TerminalClaimFailureContext | None = None,
    ) -> int:
        """Mark projection jobs as failed or return them to pending."""
        normalized = tuple(leases)
        if not normalized:
            return 0
        await self.initialize()
        host = cast(_TerminalClaimFailureHostProtocol, self)
        context = terminal_claim_failure or TerminalClaimFailureContext(
            error_type="ProjectionJobFailure",
            reason_code=(
                "pipeline_retry_budget_exhausted" if requeue else "pipeline_non_retryable_failure"
            ),
        )
        return await self._projection_queue.fail(
            leases=normalized,
            error_text=error_text,
            requeue=requeue,
            terminal_callback=_terminal_claim_callback(host, context),
        )

    async def requeue_stale_projection_jobs(
        self,
        *,
        queued_timeout_seconds: float,
        running_timeout_seconds: float,
    ) -> int:
        """Return stale queued or running jobs back to pending for replay."""
        await self.initialize()
        host = cast(_TerminalClaimFailureHostProtocol, self)
        async with self.memory_correction_job_guard():
            return await self._projection_queue.requeue_stale(
                queued_timeout_seconds=queued_timeout_seconds,
                running_timeout_seconds=running_timeout_seconds,
                terminal_callback=_terminal_claim_callback(
                    host,
                    TerminalClaimFailureContext(
                        error_type="ProjectionAttemptStale",
                        reason_code="pipeline_retry_budget_exhausted_stale",
                    ),
                ),
            )

    async def get_projection_backlog_stats(
        self,
        *,
        source_filter: str | None = None,
    ) -> Dict[str, int]:
        """Return counts for durable L2 projection jobs by status."""
        await self.initialize()
        return await self._projection_queue.get_backlog_stats(source_filter=source_filter)
