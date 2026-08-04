"""Queue worker loops for the L2 cognition pipeline."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol

from ....core.logger import get_logger
from ....events.first_context import FIRST_CONTEXT_STORY_INTERACTION_KIND
from ...event_contracts import MemoryEvent
from ..episode_formation import assign_events_to_episode, episode_type_for_event
from ..llm_json_client import L2LLMJsonError
from ..models import (
    EpisodeCandidateJob,
    L2BatchJob,
    L2FocalEntityRef,
    ReconciledTraitOutcome,
)
from ..projection.models import TerminalClaimFailureContext
from ..store import L2CognitionStore

logger = get_logger("magi.memory.l2.pipeline")


class _L2PipelineWorkerHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None
    _extract_queue: asyncio.Queue[L2BatchJob | None]
    _reconcile_queue: asyncio.Queue[list[str] | None]
    _snapshot_queue: asyncio.Queue[list[str] | None]
    _projection_consumer_name: str
    _projection_heartbeat_interval_seconds: float
    _stats: Any
    _state_change_callback: (
        Callable[[str, str, list[ReconciledTraitOutcome]], Awaitable[None]] | None
    )
    _active_entity_callback: Callable[[MemoryEvent, list[L2FocalEntityRef]], Awaitable[None]] | None

    async def _extract_and_persist(self, job: L2BatchJob) -> dict[str, Any]: ...

    def _accumulate_session_entities(
        self,
        session_id: str | None,
        entity_ids: list[str],
    ) -> None: ...

    async def enqueue_entities(self, entity_ids: list[str]) -> bool: ...

    async def enqueue_snapshot_refresh(self, entity_ids: list[str]) -> bool: ...

    async def _load_evidence_timestamps(self, entity_id: str) -> dict[str, float]: ...

    def _entity_type_from_id(self, entity_id: str) -> str: ...

    def _resolve_self_entity_id(self, event: MemoryEvent) -> str | None: ...

    def _memory_operation_guard(self) -> Any: ...

    async def _drain_event_entity_link_outbox(self) -> int: ...


class L2PipelineWorkerMixin:
    """Own the extract, reconcile, snapshot, and callback worker loops."""

    async def _run_extract_worker(self) -> None:
        host = self._worker_host()
        if host._cognition_store is None:
            return

        while True:
            job = await host._extract_queue.get()
            try:
                if job is None:
                    break
                async with host._memory_operation_guard():
                    await self._process_extract_job(job)
            finally:
                host._extract_queue.task_done()

    async def _process_extract_job(self, job: L2BatchJob) -> None:
        host = self._worker_host()
        if host._cognition_store is None:
            await self._process_extract_job_locked(job)
            return
        async with host._cognition_store.memory_correction_job_guard():
            await self._process_extract_job_locked(job)

    async def _process_extract_job_locked(self, job: L2BatchJob) -> None:
        host = self._worker_host()
        heartbeat_task: asyncio.Task[None] | None = None
        lease_lost = asyncio.Event()
        host._stats.extract_active += 1
        try:
            should_process = await self._start_extract_job(job)
            if not should_process:
                return
            if job.projection_leases and host._cognition_store is not None:
                heartbeat_task = asyncio.create_task(
                    self._run_projection_heartbeat(job, lease_lost)
                )
            result = self._validate_extract_result(await host._extract_and_persist(job))
            if lease_lost.is_set():
                raise RuntimeError("projection_attempt_fenced_during_extraction")
            await self._finish_extract_job(job, result)
            if lease_lost.is_set():
                raise RuntimeError("projection_attempt_fenced_before_completion")
            await self._stop_projection_heartbeat(heartbeat_task)
            heartbeat_task = None
            if lease_lost.is_set():
                raise RuntimeError("projection_attempt_fenced_before_completion")
            if job.projection_leases and host._cognition_store is not None:
                completed = await host._cognition_store.complete_projection_jobs(
                    job.projection_leases
                )
                if completed != len(job.projection_leases):
                    raise RuntimeError("projection_attempt_fenced_before_completion")
                await host._drain_event_entity_link_outbox()
            self._record_extract_job_completion(job, result)
        except Exception as exc:
            await self._fail_extract_job(job, exc)
        finally:
            await self._stop_projection_heartbeat(heartbeat_task)
            host._stats.extract_active = max(host._stats.extract_active - 1, 0)

    async def _start_extract_job(self, job: L2BatchJob) -> bool:
        host = self._worker_host()
        logger.info(
            "L2 extract started",
            job_id=job.job_id,
            batch_key=job.bucket_key,
            event_ids=job.event_ids,
            flush_reason=job.flush_reason,
            queue_size=host._extract_queue.qsize(),
        )
        if not job.event_ids or host._cognition_store is None:
            return True
        if not job.projection_leases:
            host._stats.extract_skipped += 1
            logger.warning(
                "L2 extract skipped without a durable projection lease",
                job_id=job.job_id,
                event_ids=job.event_ids,
            )
            return False

        transitioned = await host._cognition_store.mark_projection_jobs_running(
            job.projection_leases,
            consumer_name=host._projection_consumer_name,
        )
        if transitioned == len(job.projection_leases):
            return True

        host._stats.extract_skipped += 1
        logger.info(
            "L2 extract skipped (stale batch)",
            job_id=job.job_id,
            event_ids=job.event_ids,
            queue_size=host._extract_queue.qsize(),
        )
        return False

    async def _run_projection_heartbeat(
        self,
        job: L2BatchJob,
        lease_lost: asyncio.Event,
    ) -> None:
        """Keep a running projection batch live until its final fenced write."""

        host = self._worker_host()
        interval_seconds = max(0.001, float(host._projection_heartbeat_interval_seconds))
        while True:
            await asyncio.sleep(interval_seconds)
            if host._cognition_store is None:
                lease_lost.set()
                return
            try:
                touched = await host._cognition_store.touch_running_projection_jobs(
                    job.projection_leases
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "L2 projection heartbeat failed",
                    job_id=job.job_id,
                    event_ids=job.event_ids,
                    exc_info=True,
                )
                continue
            if touched == len(job.projection_leases):
                continue
            lease_lost.set()
            logger.warning(
                "L2 projection heartbeat lost its lease",
                job_id=job.job_id,
                event_ids=job.event_ids,
                expected_count=len(job.projection_leases),
                touched_count=touched,
            )
            return

    @staticmethod
    async def _stop_projection_heartbeat(task: asyncio.Task[None] | None) -> None:
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _validate_extract_result(result: Any) -> dict[str, Any]:
        """Normalize completion metrics before any durable completion side effect."""

        if not isinstance(result, dict):
            raise TypeError("L2 extraction result must be a mapping")
        normalized = dict(result)
        for key in (
            "relation_count",
            "assertion_count",
            "mention_count",
            "graph_candidate_count",
            "assertion_candidate_count",
            "rejected_graph_candidate_count",
            "rejected_assertion_candidate_count",
            "contradiction_hint_count",
        ):
            try:
                count = int(normalized.get(key, 0) or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"L2 extraction result has an invalid {key}") from exc
            if count < 0:
                raise ValueError(f"L2 extraction result has a negative {key}")
            normalized[key] = count
        for key in ("touched_entity_ids", "snapshot_refresh_entity_ids"):
            value = normalized.get(key, [])
            if not isinstance(value, list):
                raise TypeError(f"L2 extraction result {key} must be a list")
            normalized[key] = value
        return normalized

    async def _finish_extract_job(
        self,
        job: L2BatchJob,
        result: dict[str, Any],
    ) -> None:
        host = self._worker_host()
        touched_entity_ids = result.get("touched_entity_ids", [])
        if isinstance(touched_entity_ids, list) and touched_entity_ids:
            host._accumulate_session_entities(job.session_id, touched_entity_ids)
            await host.enqueue_entities(touched_entity_ids)

        snapshot_refresh_entity_ids = result.get("snapshot_refresh_entity_ids", [])
        if isinstance(snapshot_refresh_entity_ids, list) and snapshot_refresh_entity_ids:
            await host.enqueue_snapshot_refresh(snapshot_refresh_entity_ids)

        if job.event_ids and not result.get("skipped"):
            await self._form_episode_candidates(
                job,
                result=result,
                touched_entity_ids=touched_entity_ids,
            )

    def _record_extract_job_completion(
        self,
        job: L2BatchJob,
        result: dict[str, Any],
    ) -> None:
        host = self._worker_host()
        host._stats.extract_completed += 1
        self._log_extract_result(job, result)
        host._stats.relations_written += int(result["relation_count"])
        host._stats.assertions_written += int(result["assertion_count"])

    def _log_extract_result(self, job: L2BatchJob, result: dict[str, Any]) -> None:
        host = self._worker_host()
        if result.get("skipped"):
            host._stats.extract_skipped += 1
            logger.info(
                "L2 extract skipped",
                job_id=job.job_id,
                event_ids=job.event_ids,
                evidence_class=result.get("evidence_class"),
                skip_reason=result.get("skip_reason"),
                queue_size=host._extract_queue.qsize(),
            )
            return

        logger.info(
            "L2 extract completed",
            job_id=job.job_id,
            event_ids=job.event_ids,
            evidence_class=result.get("evidence_class"),
            profile_id=result.get("profile_id"),
            mention_count=int(result.get("mention_count", 0)),
            graph_candidate_count=int(result.get("graph_candidate_count", 0)),
            assertion_candidate_count=int(result.get("assertion_candidate_count", 0)),
            rejected_graph_candidate_count=int(result.get("rejected_graph_candidate_count", 0)),
            rejected_assertion_candidate_count=int(
                result.get("rejected_assertion_candidate_count", 0)
            ),
            relation_count=int(result["relation_count"]),
            assertion_count=int(result["assertion_count"]),
            contradiction_hint_count=int(result.get("contradiction_hint_count", 0)),
            degraded_stages=result.get("degraded_stages", []),
            touched_entity_count=len(result.get("touched_entity_ids", [])),
            queue_size=host._extract_queue.qsize(),
        )

    async def _form_episode_candidates(
        self,
        job: L2BatchJob,
        *,
        result: dict[str, Any],
        touched_entity_ids: Any,
    ) -> None:
        host = self._worker_host()
        if host._cognition_store is None:
            return
        try:
            candidate_jobs = self._build_episode_candidate_jobs(
                job,
                result=result,
                touched_entity_ids=touched_entity_ids,
            )
            if candidate_jobs:
                await assign_events_to_episode(host._cognition_store, candidate_jobs)
        except Exception:
            logger.debug("Episode candidate formation failed", exc_info=True)

    def _build_episode_candidate_jobs(
        self,
        job: L2BatchJob,
        *,
        result: dict[str, Any],
        touched_entity_ids: Any,
    ) -> list[EpisodeCandidateJob]:
        batch_entity_ids = _normalized_ids(touched_entity_ids)
        event_entity_map = _normalized_event_entity_map(result.get("event_entity_map"))
        return [
            EpisodeCandidateJob(
                event_id=eid,
                event_timestamp=float(evt.get("timestamp", 0.0) or 0.0),
                entity_ids=event_entity_map.get(eid) or batch_entity_ids,
                place_ids=result.get("touched_place_ids", []) or [],
                topic_keys=result.get("touched_topic_keys", []) or [],
                episode_type_hint=episode_type_for_event(str(evt.get("event_type") or "")),
            )
            for eid, evt in zip(job.event_ids, job.events)
            if str(
                (evt.get("metadata_json") or {}).get("interaction_kind")
                if isinstance(evt.get("metadata_json"), dict)
                else ""
            )
            .strip()
            .lower()
            != FIRST_CONTEXT_STORY_INTERACTION_KIND
        ]

    async def _fail_extract_job(self, job: L2BatchJob, exc: Exception) -> None:
        host = self._worker_host()
        if host._cognition_store is not None and job.projection_leases:
            requeue = not isinstance(exc, L2LLMJsonError)
            await host._cognition_store.fail_projection_jobs(
                job.projection_leases,
                error_text=str(exc),
                requeue=requeue,
                terminal_claim_failure=TerminalClaimFailureContext(
                    attempt_key=job.attempt_key,
                    target_id=job.job_id,
                    error_type=type(exc).__name__,
                    reason_code=(
                        "pipeline_retry_budget_exhausted"
                        if requeue
                        else "pipeline_non_retryable_failure"
                    ),
                ),
            )
            await host._drain_event_entity_link_outbox()
        host._stats.extract_failed += 1
        logger.exception(
            "L2 extract failed",
            job_id=job.job_id,
            event_ids=job.event_ids,
            queue_size=host._extract_queue.qsize(),
        )

    async def _run_reconcile_worker(self) -> None:
        host = self._worker_host()
        while True:
            entity_ids = await host._reconcile_queue.get()
            active_counted = False
            try:
                if entity_ids is None:
                    break
                async with host._memory_operation_guard():
                    host._stats.reconcile_active += 1
                    active_counted = True
                    logger.info(
                        "L2 reconcile started",
                        entity_ids=entity_ids,
                        queue_size=host._reconcile_queue.qsize(),
                    )
                    if host._cognition_store is not None:
                        async with host._cognition_store.memory_correction_job_guard():
                            snapshot_candidates, total_outcomes = await self._reconcile_entities(
                                entity_ids
                            )
                    else:
                        snapshot_candidates, total_outcomes = set(), 0
                    if snapshot_candidates:
                        await host.enqueue_snapshot_refresh(sorted(snapshot_candidates))
                    host._stats.reconcile_completed += 1
                    logger.info(
                        "L2 reconcile completed",
                        entity_ids=entity_ids,
                        outcome_count=total_outcomes,
                        snapshot_candidate_count=len(snapshot_candidates),
                        queue_size=host._reconcile_queue.qsize(),
                    )
            except Exception:
                host._stats.reconcile_failed += 1
                logger.exception(
                    "L2 reconcile failed",
                    entity_ids=entity_ids,
                    queue_size=host._reconcile_queue.qsize(),
                )
            finally:
                if active_counted:
                    host._stats.reconcile_active = max(host._stats.reconcile_active - 1, 0)
                host._reconcile_queue.task_done()

    async def _reconcile_entities(
        self,
        entity_ids: list[str],
    ) -> tuple[set[str], int]:
        host = self._worker_host()
        snapshot_candidates: set[str] = set()
        total_outcomes = 0
        if host._cognition_store is None:
            return snapshot_candidates, total_outcomes
        for entity_id in entity_ids:
            outcomes = await host._cognition_store.reconcile_entity(
                entity_id=entity_id,
                entity_type=host._entity_type_from_id(entity_id),
                evidence_timestamps=await host._load_evidence_timestamps(entity_id),
            )
            total_outcomes += len(outcomes)
            if outcomes:
                snapshot_candidates.add(entity_id)
                await self._emit_state_change_insight(
                    entity_id=entity_id,
                    entity_type=host._entity_type_from_id(entity_id),
                    outcomes=outcomes,
                )
        return snapshot_candidates, total_outcomes

    async def _emit_state_change_insight(
        self,
        *,
        entity_id: str,
        entity_type: str,
        outcomes: list[ReconciledTraitOutcome],
    ) -> None:
        host = self._worker_host()
        if host._state_change_callback is None or not outcomes:
            return
        try:
            await host._state_change_callback(entity_id, entity_type, outcomes)
        except Exception:
            logger.exception(
                "L2 state change insight callback failed",
                entity_id=entity_id,
                entity_type=entity_type,
                outcome_count=len(outcomes),
            )

    async def _emit_active_entities(
        self,
        *,
        event: MemoryEvent,
        focal_entities: list[L2FocalEntityRef],
    ) -> None:
        host = self._worker_host()
        if host._active_entity_callback is None or not focal_entities:
            return
        self_entity_id = host._resolve_self_entity_id(event)
        filtered_entities = [
            entity
            for entity in focal_entities
            if entity.entity_id and entity.entity_id != self_entity_id
        ]
        if not filtered_entities:
            return
        try:
            await host._active_entity_callback(event, filtered_entities)
        except Exception:
            logger.exception(
                "L2 active entity callback failed",
                event_id=event.event_id,
                session_id=event.session_id,
                entity_ids=[entity.entity_id for entity in filtered_entities],
            )

    async def _run_snapshot_worker(self) -> None:
        host = self._worker_host()
        while True:
            entity_ids = await host._snapshot_queue.get()
            active_counted = False
            try:
                if entity_ids is None:
                    break
                async with host._memory_operation_guard():
                    host._stats.snapshot_active += 1
                    active_counted = True
                    logger.info(
                        "L2 snapshot started",
                        entity_ids=entity_ids,
                        queue_size=host._snapshot_queue.qsize(),
                    )
                    if host._cognition_store is not None:
                        async with host._cognition_store.memory_correction_job_guard():
                            refreshed_count = await self._refresh_snapshots(entity_ids)
                    else:
                        refreshed_count = 0
                    host._stats.snapshot_completed += 1
                    logger.info(
                        "L2 snapshot completed",
                        entity_ids=entity_ids,
                        refreshed_count=refreshed_count,
                        queue_size=host._snapshot_queue.qsize(),
                    )
            except Exception:
                host._stats.snapshot_failed += 1
                logger.exception(
                    "L2 snapshot failed",
                    entity_ids=entity_ids,
                    queue_size=host._snapshot_queue.qsize(),
                )
            finally:
                if active_counted:
                    host._stats.snapshot_active = max(host._stats.snapshot_active - 1, 0)
                host._snapshot_queue.task_done()

    async def _refresh_snapshots(self, entity_ids: list[str]) -> int:
        host = self._worker_host()
        if host._cognition_store is None:
            return 0
        refreshed_count = 0
        for entity_id in entity_ids:
            snapshot = await host._cognition_store.refresh_entity_snapshot(
                entity_id=entity_id,
                entity_type=host._entity_type_from_id(entity_id),
            )
            if snapshot is not None:
                refreshed_count += 1
        return refreshed_count

    def _worker_host(self) -> _L2PipelineWorkerHostProtocol:
        return self  # type: ignore[return-value]


def _normalized_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for value in raw:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _normalized_event_entity_map(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for event_id, entity_ids in raw.items():
        key = str(event_id or "").strip()
        values = _normalized_ids(entity_ids)
        if key and values:
            normalized[key] = values
    return normalized
