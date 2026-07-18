"""Integration coverage for manual-entry source ownership during forgetting."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.core.sqlite import sqlite_connection_async
from magi.memory.forgetting import (
    SourceForgetBatch,
    SourceForgetIdentity,
    SourceForgetOwnerUnavailableError,
)
from magi.memory.manual_entries import (
    ManualEntry,
    ManualEntryL1Projector,
    ManualEntryRecoveryService,
    ManualEntryStore,
    ManualEntryWorkflow,
)
from magi.memory.manual_entries.source_forgetting import (
    ManualEntrySourceForgetOwner,
)
from magi.memory.manual_entries.workflow import (
    ManualEntryGovernanceRejectedError,
)
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.source_event_governance import (
    business_source_references,
    tombstone_source_event_ids,
)
from magi.timeline.service import _manual_asset_is_referenced


async def _build_runtime(tmp_path: Path):
    memory_db = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(memory_db))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            enable_l2_conflict_arbitration=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    store = ManualEntryStore(db_path=str(memory_db))
    owner = ManualEntrySourceForgetOwner(store=store)
    memory.register_source_forget_owner("manual_entry", owner)
    projector = ManualEntryL1Projector(memory=memory)
    workflow = ManualEntryWorkflow(
        store=store,
        projector=projector,
        memory=memory,
    )
    return memory, store, projector, workflow, owner


async def _create_projected(
    *,
    store: ManualEntryStore,
    workflow: ManualEntryWorkflow,
    entry_id: str,
    event_at: float,
    body: str,
) -> ManualEntry:
    entry = ManualEntry(
        entry_id=entry_id,
        created_at=event_at,
        event_at=event_at,
        kind="quick",
        body=body,
        attachments=[],
    )
    await store.create(entry)
    await workflow.project_and_link(
        entry=entry,
        predecessor_event_id=None,
    )
    return entry


@pytest.mark.asyncio
async def test_forgetting_old_completed_occurrence_keeps_current_entry(
    tmp_path: Path,
) -> None:
    memory, store, _, workflow, _ = await _build_runtime(tmp_path)
    try:
        original = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-old-occurrence",
            event_at=100.0,
            body="before",
        )
        old_event_id = str(original.l1_event_id)
        updated = replace(
            original,
            event_at=1_000.0,
            body="after",
        )
        await workflow.replace_and_project(
            entry=updated,
            predecessor_event_id=old_event_id,
            reason="manual_entry_update",
        )
        current_event_id = str(updated.l1_event_id)

        await memory.forget_time_range_memory(
            start=90.0,
            end=110.0,
            delete_l1_events=True,
        )

        current = await store.get(original.entry_id)
        assert current is not None
        assert current.deleted_at is None
        assert current.delete_requested_at is None
        assert current.l1_event_id == current_event_id
        current_event = await memory.l1.get_event(current_event_id)
        assert current_event is not None
        assert current_event["deleted_at"] is None

        later = replace(current, event_at=2_000.0, body="later")
        await workflow.replace_and_project(
            entry=later,
            predecessor_event_id=current_event_id,
            reason="manual_entry_update",
        )
        assert later.l1_event_id not in {old_event_id, current_event_id}
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_forgetting_pending_predecessor_keeps_pending_replacement(
    tmp_path: Path,
) -> None:
    memory, store, projector, workflow, _ = await _build_runtime(tmp_path)
    try:
        original = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-pending-occurrence",
            event_at=100.0,
            body="before",
        )
        old_event_id = str(original.l1_event_id)
        candidate = replace(
            original,
            event_at=1_000.0,
            body="after",
        )
        pending_event_id = str(
            projector.event_id_for(
                candidate,
                predecessor_event_id=old_event_id,
            )
        )
        async with projector.governed_write_guard():
            await projector.ensure_projectable_guarded(
                candidate,
                predecessor_event_id=old_event_id,
            )
            assert await store.replace_and_reserve_l1_projection(
                candidate,
                pending_event_id,
                expected_previous_event_id=old_event_id,
            )
            candidate.pending_l1_event_id = pending_event_id
            candidate.pending_l1_predecessor_event_id = old_event_id
            assert (
                await projector.project_current_guarded(
                    candidate,
                    predecessor_event_id=old_event_id,
                )
                == pending_event_id
            )

        await memory.forget_time_range_memory(
            start=90.0,
            end=110.0,
            delete_l1_events=True,
        )

        pending = await store.get(original.entry_id)
        assert pending is not None
        assert pending.deleted_at is None
        assert pending.delete_requested_at is None
        assert pending.pending_l1_event_id == pending_event_id
        assert await workflow.repair_projection_if_needed(
            entry=pending,
            reason="manual_entry_recovery",
        )
        repaired = await store.get(original.entry_id)
        assert repaired is not None
        assert repaired.deleted_at is None
        assert repaired.l1_event_id == pending_event_id
        assert repaired.pending_l1_event_id is None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_current_occurrence_forget_finalizes_source_in_same_operation(
    tmp_path: Path,
) -> None:
    memory, store, _, workflow, owner = await _build_runtime(tmp_path)
    try:
        entry = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-current-occurrence",
            event_at=100.0,
            body="private",
        )
        event_id = str(entry.l1_event_id)
        gate_results = []
        original_gate = owner.gate
        finalized_claims = []
        original_finalize = owner.finalize

        async def record_gate(batch):
            result = await original_gate(batch)
            gate_results.append(result)
            return result

        async def record_finalize(claims):
            finalized_claims.append(claims)
            await original_finalize(claims)

        owner.gate = record_gate
        owner.finalize = record_finalize

        assert (
            await memory.forget_known_source_events(
                [event_id],
                reason="external_user_forget",
                block_source_item=True,
            )
            == 1
        )
        assert len(gate_results) == 1
        async with sqlite_connection_async(memory.memory_db_path) as db:
            async with db.execute(
                """
                SELECT ref_type, source_ref
                FROM memory_forget_operation_refs
                WHERE ref_type = 'source_owner'
                """
            ) as cursor:
                source_owner_refs = await cursor.fetchall()
        assert source_owner_refs
        assert len(finalized_claims) == 1

        deleted = await store.get(entry.entry_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
        assert deleted.delete_requested_at is None
        assert deleted.l1_event_id is None
        event = await memory.l1.get_event(event_id)
        assert event is not None
        assert event["deleted_at"] is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_unlinked_active_source_is_gated_by_selected_l1_identity(
    tmp_path: Path,
) -> None:
    memory, store, projector, _, _ = await _build_runtime(tmp_path)
    try:
        entry = ManualEntry(
            entry_id="me-unlinked-legacy-source",
            created_at=100.0,
            event_at=100.0,
            kind="quick",
            body="private unlinked source",
            attachments=[],
        )
        await store.create(entry)
        event_id = await projector.project_current(
            entry,
            predecessor_event_id=None,
        )
        active = await store.get(entry.entry_id)
        assert active is not None
        assert active.l1_event_id is None
        assert active.pending_l1_event_id is None

        assert (
            await memory.forget_known_source_events(
                [event_id],
                reason="external_user_forget",
                block_source_item=True,
            )
            == 1
        )

        deleted = await store.get(entry.entry_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
        assert deleted.delete_requested_at is None
        event = await memory.l1.get_event(event_id)
        assert event is not None
        assert event["deleted_at"] is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved_before_l1", [False, True])
async def test_time_range_forget_immediately_hides_source_without_l1_event(
    tmp_path: Path,
    reserved_before_l1: bool,
) -> None:
    memory, store, projector, _, _ = await _build_runtime(tmp_path)
    try:
        asset_ref = "manual-entry-asset://private.png"
        entry = ManualEntry(
            entry_id="me-unprojected-time-range",
            created_at=100.0,
            event_at=100.0,
            kind="quick",
            body="private before projection",
            attachments=[asset_ref],
        )
        await store.create(entry)
        if reserved_before_l1:
            pending_event_id = projector.event_id_for(
                entry,
                predecessor_event_id=None,
            )
            assert pending_event_id is not None
            assert await store.reserve_l1_projection(
                entry.entry_id,
                pending_event_id,
                expected_previous_event_id=None,
            )

        await memory.forget_time_range_memory(
            start=90.0,
            end=110.0,
            delete_l1_events=True,
        )

        active = await store.get(entry.entry_id)
        assert active is not None
        assert active.deleted_at is None
        assert active.delete_requested_at is None
        assert active.l1_event_id is None
        assert bool(active.pending_l1_event_id) is reserved_before_l1
        assert (
            await store.list_window(
                time_start=0.0,
                time_end=1_000.0,
            )
            == []
        )
        assert not await _manual_asset_is_referenced(
            db_path=store.db_path,
            asset_ref=asset_ref,
        )

        recovery = ManualEntryRecoveryService(
            store=store,
            projector=projector,
            memory=memory,
            interval_seconds=0,
        )
        stats = await recovery.start()
        assert stats.recovered == 1
        deleted = await store.get(entry.entry_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_missing_required_owner_defers_then_resumes_exact_source(
    tmp_path: Path,
) -> None:
    memory, store, _, workflow, owner = await _build_runtime(tmp_path)
    try:
        entry = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-owner-recovery",
            event_at=100.0,
            body="private",
        )
        event_id = str(entry.l1_event_id)
        memory.unregister_source_forget_owner("manual_entry")

        with pytest.raises(SourceForgetOwnerUnavailableError):
            await memory.forget_known_source_events(
                [event_id],
                reason="external_user_forget",
                block_source_item=True,
            )

        with pytest.raises(SourceForgetOwnerUnavailableError):
            await memory.resume_pending_forget_operations(
                force=True,
                fail_on_barrier_error=True,
            )

        active = await store.get(entry.entry_id)
        assert active is not None
        assert active.deleted_at is None
        assert active.delete_requested_at is None

        memory.register_source_forget_owner("manual_entry", owner)
        stats = await memory.resume_pending_forget_operations(
            force=True,
            fail_on_barrier_error=True,
        )
        assert stats == {"found": 1, "completed": 1, "failed": 0}
        deleted = await store.get(entry.entry_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_missing_manual_source_does_not_downgrade_source_barrier(
    tmp_path: Path,
) -> None:
    memory, _, _, _, owner = await _build_runtime(tmp_path)
    try:
        result = await owner.gate(
            SourceForgetBatch(
                operation_id="forget:test-missing-source",
                selector_kind="known_events",
                identities=(
                    SourceForgetIdentity(
                        event_id="event-missing-source",
                        source="manual_entry",
                        source_item_id="me-missing-source",
                    ),
                ),
                reason="external_user_forget",
                block_source_item=True,
            )
        )
        assert result.claims == ()
        assert result.exact_only_event_ids == ()
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_source_reference_preflight_terminalizes_active_source(
    tmp_path: Path,
) -> None:
    memory, store, _, workflow, _ = await _build_runtime(tmp_path)
    try:
        entry = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-source-reference-retry",
            event_at=1_000.0,
            body="before",
        )
        source_item_ref = next(
            reference
            for reference in business_source_references(
                source="manual_entry",
                event_type="manual_entry.note",
                source_item_id=entry.entry_id,
                idempotency_key=None,
            )
            if reference.startswith("source-item:")
        )
        async with sqlite_connection_async(memory.memory_db_path) as db:
            await tombstone_source_event_ids(
                db,
                event_ids=(source_item_ref,),
                reason="external_user_forget",
                created_at=1_500.0,
            )
            await db.commit()
        candidate = replace(entry, event_at=2_000.0, body="after")

        with pytest.raises(ManualEntryGovernanceRejectedError) as error:
            await workflow.replace_and_project(
                entry=candidate,
                predecessor_event_id=entry.l1_event_id,
                reason="manual_entry_update",
            )

        assert error.value.reason == "source_reference"
        assert error.value.retry_as_new is True
        assert error.value.source_preserved is False
        deleted = await store.get(entry.entry_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_update_loaded_before_external_forget_requires_new_identity(
    tmp_path: Path,
) -> None:
    memory, store, _, workflow, _ = await _build_runtime(tmp_path)
    try:
        entry = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-loaded-before-forget",
            event_at=1_000.0,
            body="before",
        )
        loaded_candidate = replace(
            entry,
            event_at=2_000.0,
            body="after",
        )
        await memory.forget_known_source_events(
            [str(entry.l1_event_id)],
            reason="external_user_forget",
            block_source_item=True,
        )

        with pytest.raises(ManualEntryGovernanceRejectedError) as error:
            await workflow.replace_and_project(
                entry=loaded_candidate,
                predecessor_event_id=entry.l1_event_id,
                reason="manual_entry_update",
            )

        assert error.value.retry_as_new is True
        assert error.value.source_preserved is False
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_time_range_barrier_preserves_source_for_patch_retry(
    tmp_path: Path,
) -> None:
    memory, store, _, workflow, _ = await _build_runtime(tmp_path)
    try:
        entry = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-time-range-retry",
            event_at=1_000.0,
            body="before",
        )
        original_event_id = str(entry.l1_event_id)
        await memory.forget_time_range_memory(
            start=90.0,
            end=110.0,
            delete_l1_events=True,
        )
        blocked_candidate = replace(
            entry,
            event_at=100.0,
            body="blocked",
        )

        with pytest.raises(ManualEntryGovernanceRejectedError) as error:
            await workflow.replace_and_project(
                entry=blocked_candidate,
                predecessor_event_id=original_event_id,
                reason="manual_entry_update",
            )

        assert error.value.reason == "time_range"
        assert error.value.source_preserved is True
        assert error.value.retry_as_new is False
        preserved = await store.get(entry.entry_id)
        assert preserved is not None
        assert preserved.deleted_at is None
        assert preserved.event_at == 1_000.0
        assert preserved.body == "before"
        assert preserved.l1_event_id == original_event_id
        assert preserved.pending_l1_event_id is None

        allowed_candidate = replace(
            preserved,
            event_at=2_000.0,
            body="allowed",
        )
        await workflow.replace_and_project(
            entry=allowed_candidate,
            predecessor_event_id=original_event_id,
            reason="manual_entry_update",
        )
        assert allowed_candidate.l1_event_id != original_event_id
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_update_that_writes_first_reports_terminal_external_forget(
    tmp_path: Path,
) -> None:
    memory, store, projector, workflow, _ = await _build_runtime(tmp_path)
    try:
        entry = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-update-first",
            event_at=1_000.0,
            body="before",
        )
        candidate = replace(entry, event_at=2_000.0, body="after")
        predecessor_cleanup_started = asyncio.Event()
        continue_predecessor_cleanup = asyncio.Event()
        original_forget = workflow.forget_event_ids

        async def pause_predecessor_cleanup(
            *,
            event_ids: list[str],
            reason: str,
            block_source_item: bool,
        ) -> None:
            if reason == "manual_entry_update":
                predecessor_cleanup_started.set()
                await continue_predecessor_cleanup.wait()
            await original_forget(
                event_ids=event_ids,
                reason=reason,
                block_source_item=block_source_item,
            )

        workflow.forget_event_ids = pause_predecessor_cleanup
        update_task = asyncio.create_task(
            workflow.replace_and_project(
                entry=candidate,
                predecessor_event_id=entry.l1_event_id,
                reason="manual_entry_update",
            )
        )
        await asyncio.wait_for(
            predecessor_cleanup_started.wait(),
            timeout=2.0,
        )
        pending = await store.get(entry.entry_id)
        assert pending is not None
        pending_event_id = str(pending.pending_l1_event_id)
        await memory.forget_known_source_events(
            [pending_event_id],
            reason="external_user_forget",
            block_source_item=True,
        )
        continue_predecessor_cleanup.set()

        with pytest.raises(ManualEntryGovernanceRejectedError) as error:
            await update_task
        assert error.value.retry_as_new is True
        assert error.value.source_preserved is False
        deleted = await store.get(entry.entry_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_update_then_time_range_forget_reports_time_range_terminalization(
    tmp_path: Path,
) -> None:
    memory, store, _, workflow, _ = await _build_runtime(tmp_path)
    try:
        entry = await _create_projected(
            store=store,
            workflow=workflow,
            entry_id="me-update-time-range-race",
            event_at=1_000.0,
            body="before",
        )
        candidate = replace(entry, event_at=100.0, body="after")
        predecessor_cleanup_started = asyncio.Event()
        continue_predecessor_cleanup = asyncio.Event()
        original_forget = workflow.forget_event_ids

        async def pause_predecessor_cleanup(
            *,
            event_ids: list[str],
            reason: str,
            block_source_item: bool,
        ) -> None:
            if reason == "manual_entry_update":
                predecessor_cleanup_started.set()
                await continue_predecessor_cleanup.wait()
            await original_forget(
                event_ids=event_ids,
                reason=reason,
                block_source_item=block_source_item,
            )

        workflow.forget_event_ids = pause_predecessor_cleanup
        update_task = asyncio.create_task(
            workflow.replace_and_project(
                entry=candidate,
                predecessor_event_id=entry.l1_event_id,
                reason="manual_entry_update",
            )
        )
        await asyncio.wait_for(
            predecessor_cleanup_started.wait(),
            timeout=2.0,
        )
        await memory.forget_time_range_memory(
            start=90.0,
            end=110.0,
            delete_l1_events=True,
        )
        continue_predecessor_cleanup.set()

        with pytest.raises(ManualEntryGovernanceRejectedError) as error:
            await update_task
        assert error.value.reason == "time_range"
        assert error.value.retry_as_new is True
        assert error.value.source_preserved is False
        deleted = await store.get(entry.entry_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
    finally:
        await memory.shutdown()
