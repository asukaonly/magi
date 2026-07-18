"""Resumable state machine for cross-layer forget operations."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from .cleanup import ForgetLayerCleanup
from .models import (
    ForgetOperation,
    ForgetOutcome,
    ForgetReference,
    ForgetSelector,
    SelectedEvent,
)
from .references import ForgetReferenceBuilder
from .repository import ForgetOperationRepository
from .selectors import ForgetSelectorResolver
from .source_owners import (
    SourceForgetBatch,
    SourceForgetClaim,
    SourceForgetGateResult,
    SourceForgetIdentity,
)

logger = logging.getLogger(__name__)

_SELECTION_BATCH_SIZE = 500
_CLEANUP_BATCH_SIZE = 100
_LEASE_SECONDS = 300.0


class DurableForgetRunner:
    """Execute, checkpoint, and recover one forget operation at a time."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._repository = ForgetOperationRepository(host.memory_db_path)
        self._selectors = ForgetSelectorResolver(
            memory_db_path=host.memory_db_path,
            l1=host.l1,
        )
        self._references = ForgetReferenceBuilder(
            memory_db_path=host.memory_db_path,
            l1=host.l1,
        )
        self._cleanup = ForgetLayerCleanup(host)
        self._owner = f"forget-runner:{uuid.uuid4().hex}"
        self._run_lock = asyncio.Lock()

    async def execute(
        self,
        selector: ForgetSelector,
        *,
        reason: str,
        reuse_completed: bool,
    ) -> ForgetOutcome:
        operation = await self._repository.create_or_reuse(
            selector=selector,
            reason=reason,
            reuse_completed=reuse_completed,
        )
        if operation.completed:
            return self._outcome(operation)
        async with self._run_lock:
            self._repository.register_live_owner(self._owner)
            try:
                latest = await self._repository.get(operation.operation_id)
                if latest is None:
                    raise RuntimeError("Forget operation disappeared before execution")
                if latest.completed:
                    return self._outcome(latest)
                claimed = await self._repository.claim(
                    latest.operation_id,
                    owner=self._owner,
                    lease_seconds=_LEASE_SECONDS,
                    force=False,
                )
                if claimed is None:
                    raise RuntimeError("Forget operation is already running")
                try:
                    completed = await self._run_claimed_with_lease(claimed.operation_id)
                except BaseException as exc:
                    with suppress(RuntimeError):
                        await self._repository.mark_failed(
                            claimed.operation_id,
                            error=exc,
                        )
                    raise
                return self._outcome(completed)
            finally:
                self._repository.unregister_live_owner(self._owner)

    async def recover_pending(
        self,
        *,
        force: bool,
        fail_on_barrier_error: bool,
    ) -> dict[str, int]:
        """Resume indexed non-completed operations without scanning history."""
        stats = {"found": 0, "completed": 0, "failed": 0}
        async with self._run_lock:
            self._repository.register_live_owner(self._owner)
            try:
                after_created_at: float | None = None
                after_operation_id: str | None = None
                while True:
                    operations = await self._repository.list_recoverable(
                        force=force,
                        limit=1000,
                        after_created_at=after_created_at,
                        after_operation_id=after_operation_id,
                    )
                    if not operations:
                        break
                    stats["found"] += len(operations)
                    for operation in operations:
                        claimed = await self._repository.claim(
                            operation.operation_id,
                            owner=self._owner,
                            lease_seconds=_LEASE_SECONDS,
                            force=force,
                        )
                        if claimed is None or claimed.completed:
                            continue
                        try:
                            await self._run_claimed_with_lease(claimed.operation_id)
                            stats["completed"] += 1
                        except BaseException as exc:
                            stats["failed"] += 1
                            with suppress(RuntimeError):
                                await self._repository.mark_failed(
                                    claimed.operation_id,
                                    error=exc,
                                )
                            logger.exception(
                                "Failed to recover durable forget operation %s",
                                claimed.operation_id,
                            )
                            if fail_on_barrier_error:
                                raise
                    last = operations[-1]
                    after_created_at = last.created_at
                    after_operation_id = last.operation_id
            finally:
                self._repository.unregister_live_owner(self._owner)
        return stats

    async def has_completed_selector(self, selector: ForgetSelector) -> bool:
        return await self._repository.has_completed_selector(selector)

    async def list_pending_surface_finalizations(self) -> list[ForgetOperation]:
        """Return completed chat operations awaiting their final surface mutation."""
        return await self._repository.list_pending_surface_finalizations()

    async def mark_surface_finalized(self, operation_id: str) -> ForgetOperation:
        """Record that the chat-owned surface mutation completed."""
        return await self._repository.mark_surface_finalized(operation_id)

    async def episode_exists(self, episode_id: str) -> bool:
        return await self._selectors.episode_exists(episode_id)

    @asynccontextmanager
    async def _entity_projection_guard(
        self,
        operation: ForgetOperation,
    ) -> AsyncIterator[None]:
        """Keep entity selection and cleanup outside active L2 extraction batches."""
        l2 = self._host.l2
        if operation.selector.kind == "entity" and l2 is not None:
            async with l2.memory_correction_job_guard():
                yield
            return
        yield

    async def _run_claimed(self, operation_id: str) -> ForgetOperation:
        operation = await self._required_operation(operation_id)
        async with self._entity_projection_guard(operation):
            operation = await self._required_operation(operation_id)
            if not operation.selection_complete:
                await self._run_barrier_phase(operation)
                operation = await self._required_operation(operation_id)

            if operation.phase == "target_cleanup":
                result = await self._cleanup_target(operation)
                await self._repository.finish_target_cleanup(
                    operation.operation_id,
                    result=result,
                )
                operation = await self._required_operation(operation_id)

        if operation.phase == "source_cleanup":
            await self._run_source_cleanup(operation)
            return await self._repository.mark_completed(operation.operation_id)

        completed = await self._required_operation(operation_id)
        if not completed.completed:
            raise RuntimeError(f"Forget operation stopped in unexpected phase: {completed.phase}")
        return completed

    async def _run_claimed_with_lease(self, operation_id: str) -> ForgetOperation:
        run = asyncio.create_task(
            self._run_claimed(operation_id),
            name=f"durable-forget-run:{operation_id}",
        )
        heartbeat = asyncio.create_task(
            self._lease_heartbeat(operation_id),
            name=f"durable-forget-lease:{operation_id}",
        )
        try:
            completed_successfully = False
            done, _ = await asyncio.wait(
                (run, heartbeat),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if run in done:
                completed = await run
                completed_successfully = True
                return completed

            heartbeat_error = heartbeat.exception()
            if heartbeat_error is None:
                heartbeat_error = RuntimeError(
                    "Forget operation lease heartbeat stopped unexpectedly"
                )
            run.cancel()
            with suppress(asyncio.CancelledError):
                await run
            raise heartbeat_error
        finally:
            for task in (run, heartbeat):
                if not task.done():
                    task.cancel()
            await asyncio.gather(run, heartbeat, return_exceptions=True)
            if completed_successfully:
                self._repository.release_local_claim(operation_id)

    async def _lease_heartbeat(self, operation_id: str) -> None:
        while True:
            await asyncio.sleep(_LEASE_SECONDS / 3.0)
            renewed = await self._repository.renew_claim(
                operation_id,
                lease_seconds=_LEASE_SECONDS,
            )
            if not renewed:
                await asyncio.Event().wait()

    async def _run_barrier_phase(self, operation: ForgetOperation) -> None:
        host = self._host
        async with host._write_lock:
            time_range_target_id = await self._repository.persist_time_range_barrier(operation)
            selector_references = await self._references.selector_references(operation.selector)
            await self._repository.persist_selector_references(
                operation.operation_id,
                references=selector_references,
                reason=operation.reason,
            )
            current = await self._required_operation(operation.operation_id)
            if not current.projection_selection_complete:
                try:
                    decoded_cursors = json.loads(current.projection_cursor or "{}")
                except (TypeError, ValueError):
                    decoded_cursors = {}
                projection_cursors = decoded_cursors if isinstance(decoded_cursors, dict) else {}
                for selection in self._selectors.projection_selections(current.selector):
                    after_projection_event_id = str(projection_cursors.get(selection.scope) or "")
                    while True:
                        projection_event_ids = await self._selectors.list_projection_event_page(
                            current.selector,
                            scope=selection.scope,
                            after_event_id=after_projection_event_id,
                            limit=_SELECTION_BATCH_SIZE,
                            created_before=current.created_at,
                        )
                        if not projection_event_ids:
                            break
                        after_projection_event_id = projection_event_ids[-1]
                        projection_cursors[selection.scope] = after_projection_event_id
                        projection_block_ids = projection_event_ids
                        if selection.scope == "time_range":
                            resolved_references = await self._references.event_references(
                                projection_event_ids,
                                include_turn_references=True,
                                block_source_item=False,
                            )
                            projection_block_ids = list(
                                dict.fromkeys(
                                    reference.value
                                    for reference in resolved_references
                                    if reference.role == "cleanup"
                                )
                            )
                            await self._hide_l1_events(
                                tuple(
                                    dict.fromkeys(
                                        reference.value
                                        for reference in resolved_references
                                        if reference.ref_type == "audit_event"
                                    )
                                )
                            )
                        await self._repository.persist_projection_block_page(
                            current.operation_id,
                            block_kind=selection.block_kind,
                            target_id=(
                                time_range_target_id
                                if selection.scope == "time_range"
                                and time_range_target_id is not None
                                else selection.target_id
                            ),
                            event_ids=projection_block_ids,
                            cursor=json.dumps(
                                projection_cursors,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        )
                await self._repository.finish_projection_selection(current.operation_id)
            await self._hide_persisted_events(operation.operation_id)

            current = await self._required_operation(operation.operation_id)
            after_event_id = current.cursor
            include_turn, block_source_item = self._selectors.event_reference_options(
                current.selector
            )
            while True:
                selected_events = await self._selectors.list_event_page(
                    current.selector,
                    after_event_id=after_event_id,
                    limit=_SELECTION_BATCH_SIZE,
                )
                if not selected_events:
                    break
                selected_event_ids = [
                    event.event_id for event in selected_events
                ]
                event_ids = list(selected_event_ids)
                source_gate = SourceForgetGateResult()
                if block_source_item:
                    source_identities = await self._source_identities(event_ids)
                    gate_source_owners = getattr(
                        self._host,
                        "_notify_source_forget_owners",
                        None,
                    )
                    if callable(gate_source_owners):
                        source_gate = await gate_source_owners(
                            SourceForgetBatch(
                                operation_id=current.operation_id,
                                selector_kind=current.selector.kind,
                                identities=source_identities,
                                reason=current.reason,
                                block_source_item=True,
                            )
                        )
                    claimed_event_ids = {
                        event_id
                        for claim in source_gate.claims
                        for event_id in claim.event_ids
                    }
                    extra_event_ids = sorted(
                        claimed_event_ids - set(event_ids)
                    )
                    if extra_event_ids:
                        active_states = (
                            await self._host.l1.get_raw_event_active_states(
                                extra_event_ids
                            )
                            if self._host.l1 is not None
                            else {}
                        )
                        selected_events.extend(
                            SelectedEvent(
                                event_id=event_id,
                                was_active=bool(active_states.get(event_id)),
                            )
                            for event_id in extra_event_ids
                        )
                        event_ids.extend(extra_event_ids)
                exact_only_event_ids = set(
                    source_gate.exact_only_event_ids
                )
                source_blocked_event_ids = [
                    event_id
                    for event_id in event_ids
                    if event_id not in exact_only_event_ids
                ]
                exact_only_event_ids = [
                    event_id
                    for event_id in event_ids
                    if event_id in exact_only_event_ids
                ]
                references = (
                    *await self._references.event_references(
                        source_blocked_event_ids,
                        include_turn_references=include_turn,
                        block_source_item=block_source_item,
                    ),
                    *await self._references.event_references(
                        exact_only_event_ids,
                        include_turn_references=include_turn,
                        block_source_item=False,
                    ),
                )
                references = (
                    *references,
                    *(
                        ForgetReference(
                            "",
                            "target",
                            "source_owner",
                            self._encode_source_claim(claim),
                        )
                        for claim in source_gate.claims
                    ),
                )
                after_event_id = selected_event_ids[-1]
                await self._repository.persist_event_page(
                    current.operation_id,
                    events=selected_events,
                    references=references,
                    reason=current.reason,
                    cursor=after_event_id,
                )
                audit_event_ids = [
                    reference.value
                    for reference in references
                    if reference.ref_type == "audit_event"
                ]
                await self._hide_l1_events((*event_ids, *audit_event_ids))
            await self._repository.finish_selection(current.operation_id)

    async def _hide_persisted_events(self, operation_id: str) -> None:
        after_event_id = ""
        while True:
            event_ids = await self._repository.list_event_ids(
                operation_id,
                after_event_id=after_event_id,
                limit=_SELECTION_BATCH_SIZE,
            )
            if not event_ids:
                break
            await self._hide_l1_events(event_ids)
            after_event_id = event_ids[-1]

        after_audit_event_id = ""
        while True:
            audit_event_ids = await self._repository.list_audit_event_ids(
                operation_id,
                after_event_id=after_audit_event_id,
                limit=_SELECTION_BATCH_SIZE,
            )
            if not audit_event_ids:
                break
            await self._hide_l1_events(audit_event_ids)
            after_audit_event_id = audit_event_ids[-1]

    async def _hide_l1_events(self, event_ids: list[str] | tuple[str, ...]) -> None:
        if self._host.l1 is not None and event_ids:
            await self._host.l1.mark_deleted_many(list(event_ids))

    async def _cleanup_target(self, operation: ForgetOperation) -> dict[str, Any]:
        selector = operation.selector
        payload = selector.payload
        if selector.kind == "entity":
            if self._host.l2 is None:
                raise RuntimeError("L2 store is required to forget an entity")
            await self._promote_entity_candidate_evidence(operation)
            result = dict(await self._host.l2.forget_entity(entity_id=str(payload["entity_id"])))
            if self._host.l2_entity_catalog is not None:
                catalog_counts = await self._host.l2_entity_catalog.forget_entity_catalog(
                    str(payload["entity_id"]),
                    operation_id=operation.operation_id,
                )
                result.update(catalog_counts)
            result.update(
                await self._cleanup.cleanup_entity_projection_sources(
                    operation.operation_id,
                    reason=operation.reason,
                )
            )
            target_result = result
        elif selector.kind == "time_range":
            if self._host.l2 is None:
                raise RuntimeError("L2 store is required to forget a time range")
            target_result = dict(
                await self._host.l2.forget_time_range(
                    start=float(payload["start"]),
                    end=float(payload["end"]),
                )
            )
            target_result[
                "projection_source_references"
            ] = await self._cleanup_time_range_projection_sources(operation)
        elif selector.kind == "episode":
            if self._host.l2 is None:
                raise RuntimeError("L2 store is required to forget an episode")
            result = await self._host.l2.forget_episode(
                episode_id=str(payload["episode_id"]),
                delete_events=bool(payload.get("delete_events")),
            )
            if result is None:
                raise RuntimeError("Episode disappeared during forget operation")
            target_result = dict(result)
        elif selector.kind == "chat_session":
            if self._host.l1 is not None:
                await self._host.l1.retire_chat_session_projection(str(payload["session_id"]))
            target_result = {}
        else:
            target_result = {}

        projection_refs = await self._repository.target_references(
            operation.operation_id,
            ref_type="chat_projection",
        )
        projections: set[tuple[str, str]] = set()
        for reference in projection_refs:
            try:
                decoded = json.loads(reference)
            except (TypeError, ValueError):
                continue
            if not isinstance(decoded, list) or len(decoded) != 2:
                continue
            user_id = str(decoded[0] or "").strip()
            session_id = str(decoded[1] or "").strip()
            if user_id and session_id:
                projections.add((user_id, session_id))

        if selector.kind != "chat_session" and self._host.l1 is not None:
            for _, session_id in sorted(projections):
                await self._host.l1.rebuild_chat_session_projection(session_id)

        if selector.kind == "entity":
            l0 = getattr(self._host, "l0", None)
            if l0 is not None:
                await l0.forget_entity(str(payload["entity_id"]))
        if selector.kind in {"chat_session", "chat_history", "chat_message"}:
            l0 = getattr(self._host, "l0", None)
            if l0 is not None:
                await l0.forget_session(str(payload["session_id"]))
        return target_result

    async def _promote_entity_candidate_evidence(
        self,
        operation: ForgetOperation,
    ) -> None:
        """Close the selection race before deleting the target's lineage rows."""
        entity_id = str(operation.selector.payload["entity_id"])
        after_event_id = ""
        while True:
            event_ids = await self._selectors.list_projection_event_page(
                operation.selector,
                scope="entity_evidence",
                after_event_id=after_event_id,
                limit=_SELECTION_BATCH_SIZE,
                created_before=operation.created_at,
            )
            if not event_ids:
                return
            await self._repository.promote_entity_projection_candidates(
                operation.operation_id,
                target_id=entity_id,
                event_ids=event_ids,
            )
            after_event_id = event_ids[-1]

    async def _cleanup_time_range_projection_sources(
        self,
        operation: ForgetOperation,
    ) -> int:
        """Remove every derivative of the selected occurrences while retaining L1."""
        cleaned = 0
        after_event_id = ""
        while True:
            event_ids = await self._repository.list_time_range_projection_event_ids(
                operation.operation_id,
                after_event_id=after_event_id,
                limit=_CLEANUP_BATCH_SIZE,
            )
            if not event_ids:
                return cleaned
            await self._cleanup_reference_batch(
                operation,
                event_ids,
                item_event_id=f"time_range_projection:{event_ids[0]}",
            )
            cleaned += len(event_ids)
            after_event_id = event_ids[-1]

    async def _run_source_cleanup(self, operation: ForgetOperation) -> None:
        await self._cleanup.cleanup_operation_archives(operation.operation_id)
        if not operation.selector_cleanup_complete:
            selector_references = await self._repository.selector_cleanup_references(
                operation.operation_id
            )
            await self._cleanup_reference_batch(
                operation,
                selector_references,
                item_event_id="",
            )
            await self._repository.mark_selector_cleanup_complete(operation.operation_id)

        while True:
            event_ids = await self._repository.list_pending_event_ids(
                operation.operation_id,
                limit=_CLEANUP_BATCH_SIZE,
            )
            if not event_ids:
                break
            references = await self._repository.cleanup_references_for_events(
                operation.operation_id,
                event_ids,
            )
            await self._cleanup_reference_batch(
                operation,
                references,
                item_event_id=event_ids[0],
            )
            await self._repository.mark_events_cleaned(
                operation.operation_id,
                event_ids,
            )
        await self._finalize_source_owner_claims(operation)

    async def _source_identities(
        self,
        event_ids: list[str],
    ) -> tuple[SourceForgetIdentity, ...]:
        if self._host.l1 is None or not event_ids:
            return ()
        raw = await self._host.l1.get_raw_event_source_identities(event_ids)
        identities: list[SourceForgetIdentity] = []
        for event_id in event_ids:
            identity = raw.get(event_id)
            if not identity:
                continue
            source = str(identity.get("source") or "").strip()
            source_item_id = str(identity.get("source_item_id") or "").strip()
            if source and source_item_id:
                identities.append(
                    SourceForgetIdentity(
                        event_id=event_id,
                        source=source,
                        source_item_id=source_item_id,
                    )
                )
        return tuple(identities)

    async def _finalize_source_owner_claims(
        self,
        operation: ForgetOperation,
    ) -> None:
        encoded_claims = await self._repository.target_references(
            operation.operation_id,
            ref_type="source_owner",
        )
        finalize_source_owners = getattr(
            self._host,
            "_finalize_source_forget_owners",
            None,
        )
        if not callable(finalize_source_owners):
            return
        claims: dict[tuple[str, str], SourceForgetClaim] = {}
        for encoded in encoded_claims:
            claim = self._decode_source_claim(encoded)
            if claim is None:
                raise RuntimeError(
                    "Persisted source-forget owner claim is invalid"
                )
            key = (claim.source, claim.source_item_id)
            previous = claims.get(key)
            claims[key] = SourceForgetClaim(
                source=claim.source,
                source_item_id=claim.source_item_id,
                event_ids=(
                    *(() if previous is None else previous.event_ids),
                    *claim.event_ids,
                ),
            )
        await finalize_source_owners(tuple(claims.values()))

    @staticmethod
    def _encode_source_claim(claim: SourceForgetClaim) -> str:
        return json.dumps(
            {
                "event_ids": list(claim.event_ids),
                "source": claim.source,
                "source_item_id": claim.source_item_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _decode_source_claim(value: str) -> SourceForgetClaim | None:
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return SourceForgetClaim(
                source=str(payload.get("source") or ""),
                source_item_id=str(payload.get("source_item_id") or ""),
                event_ids=tuple(
                    str(event_id)
                    for event_id in payload.get("event_ids", [])
                ),
            )
        except (TypeError, ValueError):
            return None

    async def _cleanup_reference_batch(
        self,
        operation: ForgetOperation,
        references: tuple[str, ...],
        *,
        item_event_id: str,
    ) -> None:
        prepared_marker = await self._repository.target_references(
            operation.operation_id,
            ref_type="entity_refresh_prepared",
            item_event_id=item_event_id,
        )
        if not prepared_marker:
            prepared_entity_ids: tuple[str, ...] = ()
            catalog = getattr(self._host, "l2_entity_catalog", None)
            if catalog is not None:
                prepared_entity_ids = await catalog.prepare_source_event_forgetting(references)
            target_refs = [
                ForgetReference(
                    item_event_id,
                    "target",
                    "entity_refresh_prepared",
                    "prepared",
                ),
                *(
                    ForgetReference(
                        item_event_id,
                        "target",
                        "entity_refresh",
                        entity_id,
                    )
                    for entity_id in prepared_entity_ids
                ),
            ]
            await self._repository.persist_selector_references(
                operation.operation_id,
                references=target_refs,
                reason=operation.reason,
            )
        prepared_entity_ids = await self._repository.target_references(
            operation.operation_id,
            ref_type="entity_refresh",
            item_event_id=item_event_id,
        )
        await self._cleanup.cleanup_references(
            references,
            reason=operation.reason,
            prepared_entity_ids=prepared_entity_ids,
            entity_refresh_started_at=time.time(),
        )

    async def _required_operation(self, operation_id: str) -> ForgetOperation:
        operation = await self._repository.get(operation_id)
        if operation is None:
            raise RuntimeError("Forget operation does not exist")
        return operation

    @staticmethod
    def _outcome(operation: ForgetOperation) -> ForgetOutcome:
        return ForgetOutcome(
            operation_id=operation.operation_id,
            selector_kind=operation.selector.kind,
            event_count=operation.active_event_count,
            target_result=operation.result,
        )


__all__ = ["DurableForgetRunner"]
