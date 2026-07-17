"""Crash-recovery coverage for durable manual-entry intents."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.memory.manual_entries import (
    ManualEntry,
    ManualEntryL1Projector,
    ManualEntryRecoveryService,
    ManualEntryStore,
    ManualEntryWorkflow,
)
from magi.memory.manual_entries.lifecycle import ManualEntriesModule
from magi.memory.operation_barrier import AsyncOperationBarrier


def _entry(entry_id: str, *, body: str) -> ManualEntry:
    return ManualEntry(
        entry_id=entry_id,
        created_at=100.0,
        event_at=100.0,
        kind="quick",
        body=body,
        attachments=[],
    )


class _FakeL1:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {}

    async def get_event(self, event_id: str):
        event = self.events.get(event_id)
        return copy.deepcopy(event) if event is not None else None


class _FakeMemory:
    def __init__(self) -> None:
        self.operation_barrier = AsyncOperationBarrier()
        self.l1 = _FakeL1()
        self.fail_forget_count = 0

    def memory_operation_guard(self):
        return self.operation_barrier.operation()

    async def store_governed_l1_event(self, event) -> str:
        async with self.memory_operation_guard():
            self.l1.events.setdefault(
                event.event_id,
                {
                    "event_id": event.event_id,
                    "source_item_id": event.source_item_id,
                    "deleted_at": None,
                },
            )
            return event.event_id

    async def forget_known_source_events(
        self,
        event_ids,
        *,
        reason: str,
        block_source_item: bool,
    ) -> int:
        async with self.memory_operation_guard():
            _ = reason, block_source_item
            if self.fail_forget_count:
                self.fail_forget_count -= 1
                raise RuntimeError("injected cleanup failure")
            changed = 0
            for event_id in dict.fromkeys(event_ids):
                event = self.l1.events.setdefault(
                    event_id,
                    {
                        "event_id": event_id,
                        "source_item_id": None,
                        "deleted_at": None,
                    },
                )
                if event["deleted_at"] is None:
                    event["deleted_at"] = 200.0
                    changed += 1
            return changed


async def _project(
    store: ManualEntryStore,
    projector: ManualEntryL1Projector,
    memory: _FakeMemory,
    entry: ManualEntry,
) -> None:
    await ManualEntryWorkflow(
        store=store,
        projector=projector,
        memory=memory,
    ).project_and_link(entry=entry, predecessor_event_id=None)


@pytest.mark.asyncio
async def test_recovery_pages_every_candidate_and_leaves_healthy_rows_untouched(
    manual_entry_db: str,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    memory = _FakeMemory()
    projector = ManualEntryL1Projector(memory=memory)

    pending = _entry("me-10-pending", body="pending")
    await store.create(pending)
    pending_id = projector.event_id_for(pending, predecessor_event_id=None)
    assert await store.reserve_l1_projection(
        pending.entry_id,
        pending_id,
        expected_previous_event_id=None,
    )
    assert await projector.project_current(pending, predecessor_event_id=None) == pending_id

    half_created = _entry("me-20-half-created", body="half created")
    await store.create(half_created)

    deleting = _entry("me-30-deleting", body="delete me")
    await store.create(deleting)
    await _project(store, projector, memory, deleting)
    deleting_event_id = deleting.l1_event_id
    assert deleting_event_id is not None
    assert await store.request_delete(deleting.entry_id, requested_at=150.0)

    healthy = _entry("me-40-healthy", body="healthy")
    await store.create(healthy)
    await _project(store, projector, memory, healthy)
    healthy_event_id = healthy.l1_event_id

    visible_before_recovery = await store.list_window(
        time_start=0.0,
        time_end=1000.0,
    )
    assert deleting.entry_id not in {entry.entry_id for entry in visible_before_recovery}

    service = ManualEntryRecoveryService(
        store=store,
        projector=projector,
        memory=memory,
        page_size=2,
        interval_seconds=0,
    )
    stats = await service.start()

    assert stats.to_dict() == {
        "scanned": 3,
        "recovered": 3,
        "failed": 0,
        "skipped": 0,
    }
    recovered_pending = await store.get(pending.entry_id)
    recovered_half = await store.get(half_created.entry_id)
    recovered_delete = await store.get(deleting.entry_id)
    recovered_healthy = await store.get(healthy.entry_id)
    assert recovered_pending is not None
    assert recovered_pending.l1_event_id == pending_id
    assert recovered_pending.pending_l1_event_id is None
    assert recovered_half is not None and recovered_half.l1_event_id is not None
    assert recovered_delete is not None and recovered_delete.deleted_at is not None
    assert memory.l1.events[deleting_event_id]["deleted_at"] is not None
    assert recovered_healthy is not None
    assert recovered_healthy.l1_event_id == healthy_event_id

    second_pass = await service.recover_pending()
    assert second_pass.scanned == 0


@pytest.mark.asyncio
async def test_failed_delete_recovery_stays_hidden_and_succeeds_on_retry(
    manual_entry_db: str,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    memory = _FakeMemory()
    projector = ManualEntryL1Projector(memory=memory)
    deleting = _entry("me-delete-retry", body="private")
    await store.create(deleting)
    await _project(store, projector, memory, deleting)
    assert await store.request_delete(deleting.entry_id, requested_at=150.0)
    memory.fail_forget_count = 1

    service = ManualEntryRecoveryService(
        store=store,
        projector=projector,
        memory=memory,
        interval_seconds=0.01,
    )
    first = await service.start()

    assert first.failed == 1
    still_pending = await store.get(deleting.entry_id)
    assert still_pending is not None
    assert still_pending.deleted_at is None
    assert still_pending.delete_requested_at is not None
    assert (
        await store.list_window(
            time_start=0.0,
            time_end=1000.0,
        )
        == []
    )

    try:
        for _ in range(50):
            deleted = await store.get(deleting.entry_id)
            if deleted is not None and deleted.deleted_at is not None:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("periodic recovery did not retry the failed deletion")
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_lifecycle_recovers_half_created_entry_before_init_returns(
    manual_entry_db: str,
    tmp_path: Path,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    entry = _entry("me-startup", body="recover during startup")
    await store.create(entry)
    memory = _FakeMemory()
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = SimpleNamespace(
        memory_db_path=Path(manual_entry_db),
        memory_dir=tmp_path / "memory",
    )
    context.memory.unified_memory = memory
    module = ManualEntriesModule(context)

    assert "runtime_memory" in module.dependencies
    await module.init()
    try:
        recovered = await context.manual_entries.store.get(entry.entry_id)
        assert recovered is not None
        assert recovered.l1_event_id is not None
        assert context.manual_entries.recovery_service is not None
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_projection_chain_blocks_exclusive_clear_until_link_is_complete(
    manual_entry_db: str,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    memory = _FakeMemory()
    projector = ManualEntryL1Projector(memory=memory)
    entry = _entry("me-projection-barrier", body="barrier")
    await store.create(entry)
    write_started = asyncio.Event()
    release_write = asyncio.Event()
    clear_entered = asyncio.Event()
    state_seen_by_clear: list[ManualEntry | None] = []
    original_write = memory.store_governed_l1_event

    async def paused_write(event) -> str:
        write_started.set()
        await release_write.wait()
        return await original_write(event)

    memory.store_governed_l1_event = paused_write

    async def clear() -> None:
        async with memory.operation_barrier.exclusive():
            state_seen_by_clear.append(await store.get(entry.entry_id))
            clear_entered.set()

    projection_task = asyncio.create_task(
        ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        ).project_and_link(
            entry=entry,
            predecessor_event_id=None,
        )
    )
    await asyncio.wait_for(write_started.wait(), timeout=1)
    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)

    assert not clear_entered.is_set()
    reserved = await store.get(entry.entry_id)
    assert reserved is not None and reserved.pending_l1_event_id is not None

    release_write.set()
    await asyncio.gather(projection_task, clear_task)

    assert clear_entered.is_set()
    assert state_seen_by_clear[0] is not None
    assert state_seen_by_clear[0].l1_event_id is not None
    assert state_seen_by_clear[0].pending_l1_event_id is None


@pytest.mark.asyncio
async def test_delete_chain_blocks_exclusive_clear_until_finalization(
    manual_entry_db: str,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    memory = _FakeMemory()
    projector = ManualEntryL1Projector(memory=memory)
    entry = _entry("me-delete-barrier", body="barrier")
    await store.create(entry)
    await _project(store, projector, memory, entry)
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    clear_entered = asyncio.Event()
    state_seen_by_clear: list[ManualEntry | None] = []
    original_forget = memory.forget_known_source_events

    async def paused_forget(event_ids, *, reason: str, block_source_item: bool) -> int:
        cleanup_started.set()
        await release_cleanup.wait()
        return await original_forget(
            event_ids,
            reason=reason,
            block_source_item=block_source_item,
        )

    memory.forget_known_source_events = paused_forget

    async def clear() -> None:
        async with memory.operation_barrier.exclusive():
            state_seen_by_clear.append(await store.get(entry.entry_id))
            clear_entered.set()

    delete_task = asyncio.create_task(
        ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        ).delete_entry(entry.entry_id)
    )
    await asyncio.wait_for(cleanup_started.wait(), timeout=1)
    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)

    assert not clear_entered.is_set()
    gated = await store.get(entry.entry_id)
    assert gated is not None and gated.delete_requested_at is not None
    assert gated.deleted_at is None

    release_cleanup.set()
    await asyncio.gather(delete_task, clear_task)

    assert clear_entered.is_set()
    assert state_seen_by_clear[0] is not None
    assert state_seen_by_clear[0].deleted_at is not None
