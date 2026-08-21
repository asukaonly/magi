"""Tests for the history import service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import aiosqlite
import pytest

from magi.db.migrations.memory_shared.versions.v36_history_imports import (
    CREATE_STATEMENTS,
)
from magi.db.migrations.memory_shared.versions.v37_history_import_selection import (
    SCHEMA_SQL as SELECTION_SCHEMA_SQL,
)
from magi.db.migrations.memory_shared.versions.v46_history_import_adapters import (
    SCHEMA_SQL as IMPORTER_SCHEMA_SQL,
)
from magi.core.operation_barrier import AsyncOperationBarrier
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports import service as history_import_service_module
from magi.memory.history_imports.service import (
    SOURCE_PREVIEW_MAX_CHARS,
    HistoryImportNotFoundError,
    HistoryImportService,
    HistoryImportValidationError,
)
from magi.memory.history_imports.models import HistoryImportJob, HistoryImportRecord
from magi.memory.history_imports.store import HistoryImportStore


class _MemoryStub:
    def __init__(self) -> None:
        self.epoch = 0
        self.raw_events: list[Any] = []
        self.projected_events: list[Any] = []
        self.forgotten_event_ids: list[str] = []
        self.operation_barrier = AsyncOperationBarrier()

    def memory_operation_guard(self):
        return self.operation_barrier.operation()

    def memory_operation_epoch(self) -> int:
        return self.epoch

    @asynccontextmanager
    async def governed_l1_write_guard(self):
        yield

    async def store_governed_l1_event_under_write_lock(self, event):
        self.raw_events.append(event)
        return event.event_id

    async def ingest_event(self, event, *, expected_epoch=None):
        if expected_epoch != self.epoch:
            return {
                "skipped": True,
                "skip_reason": "memory_clear_epoch_changed",
                "l2_job_enqueued": False,
            }
        self.projected_events.append(event)
        return {"l2_job_enqueued": True}

    async def forget_reimportable_source_events(
        self,
        event_ids,
        *,
        reason,
    ):
        self.forgotten_event_ids.extend(event_ids)


class _PausedRawMemoryStub(_MemoryStub):
    def __init__(self) -> None:
        super().__init__()
        self.raw_write_started = asyncio.Event()
        self.release_raw_write = asyncio.Event()

    async def store_governed_l1_event_under_write_lock(self, event):
        self.raw_write_started.set()
        await self.release_raw_write.wait()
        return await super().store_governed_l1_event_under_write_lock(event)


class _RetryProjectionMemoryStub(_MemoryStub):
    def __init__(self) -> None:
        super().__init__()
        self.projection_attempts = 0

    async def ingest_event(self, event, *, expected_epoch=None):
        self.projection_attempts += 1
        if self.projection_attempts == 1:
            return {
                "event_id": event.event_id,
                "l2_job_enqueued": False,
            }
        self.projected_events.append(event)
        return {
            "event_id": event.event_id,
            "l2_job_enqueued": True,
        }


class _ExistingProjectionStore:
    async def has_projection_job(self, *, event_id: str) -> bool:
        return bool(event_id)


class _ExistingProjectionMemoryStub(_MemoryStub):
    def __init__(self) -> None:
        super().__init__()
        self.l2 = _ExistingProjectionStore()

    async def ingest_event(self, event, *, expected_epoch=None):
        return {
            "event_id": event.event_id,
            "l2_job_enqueued": False,
        }


class _GovernedProjectionSkipMemoryStub(_ExistingProjectionMemoryStub):
    async def ingest_event(self, event, *, expected_epoch=None):
        return {
            "event_id": event.event_id,
            "l2_job_enqueued": False,
            "skipped_derivations": True,
            "skip_reason": "time_range_forgotten",
        }


@pytest.fixture
async def history_store(tmp_path: Path) -> HistoryImportStore:
    db_path = tmp_path / "memory.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE l2_projection_jobs(" "event_id TEXT PRIMARY KEY, source TEXT NOT NULL)"
        )
        for statement in CREATE_STATEMENTS:
            await db.execute(statement)
        await db.executescript(SELECTION_SCHEMA_SQL)
        await db.executescript(IMPORTER_SCHEMA_SQL)
        await db.commit()
    return HistoryImportStore(db_path=str(db_path))


def _build_real_memory(tmp_path: Path) -> UnifiedMemoryStore:
    return UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        archive_dir_path=str(tmp_path / "archive"),
        enable_l0=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )


async def _wait_for_completed_job(
    service: HistoryImportService,
    job_id: str,
) -> None:
    for _ in range(100):
        current = await service.get_job(job_id)
        if current.status == "completed" and job_id not in service._tasks:
            return
        await asyncio.sleep(0.01)
    pytest.fail("History import did not complete")


async def _wait_for_quick_ready_job(
    service: HistoryImportService,
    job_id: str,
) -> None:
    for _ in range(100):
        current = await service.get_job(job_id)
        if current.quick_ready:
            return
        await asyncio.sleep(0.01)
    pytest.fail("History import did not reach quick ready")


@pytest.mark.asyncio
async def test_confirm_projects_chat_shaped_markdown_as_one_personal_document(
    tmp_path: Path,
    history_store: HistoryImportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        history_import_service_module,
        "local_calendar_timezone_id",
        lambda: "Asia/Shanghai",
    )
    markdown = tmp_path / "chat.md"
    markdown.write_text(
        """
## 2026-07-01
- [09:00] Me: I started learning pottery.
- [09:01] Alice: What do you like about it?
- [09:02] Me: It helps me slow down.
- [09:03] Alice: That sounds peaceful.
""",
        encoding="utf-8",
    )
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    preview = await service.preview_markdown_paths([str(markdown)])
    assert preview.detected_kind == "document"
    assert preview.total_records == 1
    assert {item.participant_id for item in preview.participants} == {"__document_author__"}

    ready = await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_source_ids=preview.included_source_ids,
    )
    assert ready.quick_ready is True
    assert ready.quick_imported_count == 1

    for _ in range(50):
        current = await service.get_job(preview.job_id)
        if current.status == "completed":
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("History import did not complete")

    expected_content = markdown.read_text(encoding="utf-8").strip()
    assert [event.content for event in memory.projected_events] == [expected_content]
    assert [event.content for event in memory.raw_events] == [expected_content]
    first_event = memory.raw_events[0]
    assert first_event.metadata_json["history_import"]["timestamp_anchor_source"] == ("file_mtime")
    assert first_event.metadata_json["_temporal"]["calendar_timezone_id"] == ("Asia/Shanghai")

    from magi.memory.l2.batch_models import L2BatchEvent, L2EventWindow
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile
    from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt
    from magi.memory.l2.pipeline.source_time_policy import resolve_event_time_semantics

    profile = resolve_extraction_profile(first_event)
    time_semantics = resolve_event_time_semantics(first_event)
    prompt = render_phase1_extract_prompt(
        event_window=L2EventWindow(events=[L2BatchEvent.from_dict(first_event.to_dict())]),
        focal_subject={"entity_ref": "user:local-user", "entity_type": "user"},
        extraction_instructions=profile.phase1_instructions,
    )

    assert profile.profile_id == "history_import.document"
    assert "historical documents, not live chat turns" in str(profile.phase1_instructions)
    assert time_semantics.timestamp_quality == "approximate_recorded"
    assert time_semantics.timestamp_anchor_source == "file_mtime"
    assert expected_content in prompt
    await service.stop()


@pytest.mark.asyncio
async def test_running_progress_reads_do_not_hydrate_preview_details(
    tmp_path: Path,
    history_store: HistoryImportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = tmp_path / "journal.md"
    markdown.write_text("I started learning pottery this week.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())
    preview = await service.preview_markdown_paths([str(markdown)])
    assert preview.participants
    assert preview.sources
    await history_store.mark_running(job_id=preview.job_id)

    async def fail_hydration(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Progress reads must not hydrate preview details")

    monkeypatch.setattr(history_store, "get_job", fail_hydration)

    progress = await service.get_job(preview.job_id)
    active = await service.list_jobs()

    assert progress.status == "running"
    assert progress.participants == []
    assert progress.sources == []
    assert progress.preview_records == []
    assert [job.job_id for job in active] == [preview.job_id]
    await service.stop()


@pytest.mark.asyncio
async def test_background_checkpoints_use_lightweight_progress_reads(
    tmp_path: Path,
    history_store: HistoryImportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        history_import_service_module,
        "local_calendar_timezone_id",
        lambda: "Asia/Shanghai",
    )
    markdown = tmp_path / "journal.md"
    markdown.write_text("I started learning pottery this week.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)
    preview = await service.preview_markdown_paths([str(markdown)])
    monkeypatch.setattr(service, "_start_background", lambda _job_id: None)
    await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_source_ids=preview.included_source_ids,
    )

    async def fail_hydration(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Background work must not hydrate preview details")

    monkeypatch.setattr(history_store, "get_job", fail_hydration)

    await service._run_background(preview.job_id)

    completed = await history_store.get_job_progress(preview.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.participants == []
    assert completed.sources == []
    assert len(memory.projected_events) == 1
    await service.stop()


@pytest.mark.asyncio
async def test_cancelled_confirmation_request_does_not_cancel_quick_import(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "journal.md"
    markdown.write_text("I started learning pottery this week.", encoding="utf-8")
    memory = _PausedRawMemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)
    confirm_task: asyncio.Task[HistoryImportJob] | None = None

    try:
        preview = await service.preview_markdown_paths([str(markdown)])
        confirm_task = asyncio.create_task(
            service.confirm(
                job_id=preview.job_id,
                confirm_personal_writing=True,
                included_source_ids=preview.included_source_ids,
            )
        )
        await asyncio.wait_for(memory.raw_write_started.wait(), timeout=1)

        confirm_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await confirm_task

        quick_task = service._quick_tasks.get(preview.job_id)
        assert quick_task is not None
        assert quick_task.cancelled() is False

        memory.release_raw_write.set()
        await _wait_for_completed_job(service, preview.job_id)
        completed = await service.get_job(preview.job_id)

        assert completed.quick_ready is True
        assert completed.quick_imported_count == 1
        assert len(memory.raw_events) == 1
    finally:
        memory.release_raw_write.set()
        if confirm_task is not None and not confirm_task.done():
            confirm_task.cancel()
            await asyncio.gather(confirm_task, return_exceptions=True)
        await service.stop()


@pytest.mark.asyncio
async def test_start_recovers_partially_finished_quick_import_without_rewriting_l1(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("I started learning pottery.", encoding="utf-8")
    second.write_text("I signed up for another class.", encoding="utf-8")
    memory = _MemoryStub()
    initial_service = HistoryImportService(store=history_store, memory=memory)
    recovered_service: HistoryImportService | None = None

    try:
        preview = await initial_service.preview_markdown_paths([str(first), str(second)])
        await history_store.set_scope(
            job_id=preview.job_id,
            self_participant_ids=["__document_author__"],
            included_source_ids=preview.included_source_ids,
        )
        quick_records = await history_store.select_quick_records(job_id=preview.job_id)
        await initial_service._store_raw_record(
            quick_records[0],
            quick=True,
            expected_epoch=memory.memory_operation_epoch(),
        )
        await initial_service.stop()

        recovered_service = HistoryImportService(store=history_store, memory=memory)
        await recovered_service.start()
        await _wait_for_completed_job(recovered_service, preview.job_id)
        completed = await recovered_service.get_job(preview.job_id)

        assert completed.quick_ready is True
        assert completed.quick_imported_count == 2
        assert len(memory.raw_events) == 2
        assert len({event.event_id for event in memory.raw_events}) == 2
    finally:
        if recovered_service is not None:
            await recovered_service.stop()
        else:
            await initial_service.stop()


@pytest.mark.asyncio
async def test_resume_restarts_failed_confirmed_quick_import(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "journal.md"
    markdown.write_text("I started learning pottery this week.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    try:
        preview = await service.preview_markdown_paths([str(markdown)])
        await history_store.set_scope(
            job_id=preview.job_id,
            self_participant_ids=["__document_author__"],
            included_source_ids=preview.included_source_ids,
        )
        await history_store.mark_failed(
            job_id=preview.job_id,
            error_text="InterruptedError",
        )

        resumed = await service.resume(preview.job_id)
        assert resumed.status == "running"
        assert resumed.quick_ready is False

        await _wait_for_completed_job(service, preview.job_id)
        completed = await service.get_job(preview.job_id)
        assert completed.quick_ready is True
        assert completed.quick_imported_count == 1
        assert len(memory.raw_events) == 1
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_completed_import_retries_a_skipped_memory_handoff(
    tmp_path: Path,
    history_store: HistoryImportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        history_import_service_module,
        "local_calendar_timezone_id",
        lambda: "Asia/Shanghai",
    )
    markdown = tmp_path / "journal.md"
    markdown.write_text("I started learning pottery this week.", encoding="utf-8")
    memory = _RetryProjectionMemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    try:
        preview = await service.preview_markdown_paths([str(markdown)])
        await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )
        await _wait_for_completed_job(service, preview.job_id)
        first_pass = await service.get_job(preview.job_id)

        assert first_pass.imported_count == 1
        assert first_pass.projected_count == 0
        assert memory.projection_attempts == 1
        assert len(memory.raw_events) == 1

        resumed = await service.resume(preview.job_id)
        assert resumed.status == "running"
        await _wait_for_completed_job(service, preview.job_id)
        completed = await service.get_job(preview.job_id)

        assert completed.imported_count == 1
        assert completed.projected_count == 1
        assert memory.projection_attempts == 2
        assert len(memory.raw_events) == 1
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_existing_l2_job_counts_as_a_completed_memory_handoff(
    tmp_path: Path,
    history_store: HistoryImportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        history_import_service_module,
        "local_calendar_timezone_id",
        lambda: "Asia/Shanghai",
    )
    markdown = tmp_path / "journal.md"
    markdown.write_text("I started learning pottery this week.", encoding="utf-8")
    memory = _ExistingProjectionMemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    try:
        preview = await service.preview_markdown_paths([str(markdown)])
        await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )
        await _wait_for_completed_job(service, preview.job_id)
        completed = await service.get_job(preview.job_id)

        assert completed.imported_count == 1
        assert completed.projected_count == 1
        resumed = await service.resume(preview.job_id)
        assert resumed.status == "completed"
        assert resumed.projected_count == 1
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_governed_skip_is_not_overridden_by_an_existing_l2_job(
    tmp_path: Path,
    history_store: HistoryImportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        history_import_service_module,
        "local_calendar_timezone_id",
        lambda: "Asia/Shanghai",
    )
    markdown = tmp_path / "journal.md"
    markdown.write_text("I started learning pottery this week.", encoding="utf-8")
    memory = _GovernedProjectionSkipMemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    try:
        preview = await service.preview_markdown_paths([str(markdown)])
        await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )
        await _wait_for_completed_job(service, preview.job_id)
        completed = await service.get_job(preview.job_id)

        assert completed.imported_count == 1
        assert completed.projected_count == 0
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_preview_disambiguates_same_named_files_without_full_paths(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    first = tmp_path / "journal" / "notes.md"
    second = tmp_path / "archive" / "notes.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("# 2026-07-01\nA day at the lake.", encoding="utf-8")
    second.write_text("# 2026-07-02\nAn evening concert.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    preview = await service.preview_markdown_paths([str(first), str(second)])

    assert len(preview.source_ids) == 2
    assert len(set(preview.source_ids)) == 2
    assert all(str(tmp_path) not in source_name for source_name in preview.source_ids)


@pytest.mark.asyncio
async def test_delete_forgets_every_imported_raw_event(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "notes.md"
    markdown.write_text("# Notes\n\nI am learning pottery.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)
    preview = await service.preview_markdown_paths([str(markdown)])
    await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_source_ids=preview.included_source_ids,
    )
    await service.delete(preview.job_id)

    deleted = await service.get_job(preview.job_id)
    assert deleted.status == "deleted"
    assert deleted.source_type == "deleted"
    assert deleted.source_fingerprint == f"deleted:{preview.job_id}"
    assert deleted.source_ids == []
    assert deleted.included_source_ids == []
    assert deleted.self_participant_ids == []
    assert deleted.warnings == []
    assert deleted.total_records == 0
    assert memory.forgotten_event_ids == [memory.raw_events[0].event_id]
    with pytest.raises(HistoryImportNotFoundError):
        await service.get_source_preview(
            job_id=preview.job_id,
            source_id="notes.md",
        )
    async with aiosqlite.connect(history_store.db_path) as db:
        membership_count = (
            await (
                await db.execute(
                    "SELECT COUNT(*) FROM history_import_job_records WHERE job_id = ?",
                    (preview.job_id,),
                )
            ).fetchone()
        )[0]
        source_count = (
            await (
                await db.execute("SELECT COUNT(*) FROM history_import_source_records")
            ).fetchone()
        )[0]
    assert membership_count == 0
    assert source_count == 0
    await service.stop()


@pytest.mark.asyncio
async def test_partial_file_change_reuses_unchanged_source_record_identity(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    unchanged = tmp_path / "unchanged.md"
    changed = tmp_path / "changed.md"
    unchanged.write_text("# Notes\n\nI keep learning pottery.", encoding="utf-8")
    changed.write_text("# Notes\n\nFirst version.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    first = await service.preview_markdown_paths([str(unchanged), str(changed)])
    first_unchanged = (
        await history_store.list_source_records(
            job_id=first.job_id,
            source_id="unchanged.md",
            limit=10,
        )
    )[0]
    first_changed = (
        await history_store.list_source_records(
            job_id=first.job_id,
            source_id="changed.md",
            limit=10,
        )
    )[0]

    changed.write_text("# Notes\n\nSecond version.", encoding="utf-8")
    second = await service.preview_markdown_paths([str(unchanged), str(changed)])
    second_unchanged = (
        await history_store.list_source_records(
            job_id=second.job_id,
            source_id="unchanged.md",
            limit=10,
        )
    )[0]
    second_changed = (
        await history_store.list_source_records(
            job_id=second.job_id,
            source_id="changed.md",
            limit=10,
        )
    )[0]

    assert second.job_id != first.job_id
    assert second_unchanged.source_record_key == first_unchanged.source_record_key
    assert second_unchanged.event_id == first_unchanged.event_id
    assert second_unchanged.session_id == first_unchanged.session_id
    assert second_unchanged.job_record_id != first_unchanged.job_record_id
    assert second_changed.source_record_key != first_changed.source_record_key
    assert second_changed.event_id != first_changed.event_id

    async with aiosqlite.connect(history_store.db_path) as db:
        source_count = (
            await (
                await db.execute("SELECT COUNT(*) FROM history_import_source_records")
            ).fetchone()
        )[0]
        membership_count = (
            await (await db.execute("SELECT COUNT(*) FROM history_import_job_records")).fetchone()
        )[0]
    assert source_count == 3
    assert membership_count == 4


@pytest.mark.asyncio
async def test_concurrent_identical_file_selection_reuses_existing_job(
    tmp_path: Path,
    history_store: HistoryImportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = tmp_path / "notes.md"
    markdown.write_text("# Notes\n\nStable content.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())
    original_find = history_store.find_active_by_fingerprint
    both_reads_completed = asyncio.Event()
    find_lock = asyncio.Lock()
    find_count = 0

    async def synchronized_find(fingerprint: str) -> Any:
        nonlocal find_count
        existing = await original_find(fingerprint)
        async with find_lock:
            find_count += 1
            if find_count == 2:
                both_reads_completed.set()
        await asyncio.wait_for(both_reads_completed.wait(), timeout=1)
        return existing

    monkeypatch.setattr(history_store, "find_active_by_fingerprint", synchronized_find)

    first, second = await asyncio.gather(
        service.preview_markdown_paths([str(markdown)]),
        service.preview_markdown_paths([str(markdown)]),
    )

    assert second.job_id == first.job_id
    async with aiosqlite.connect(history_store.db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM history_import_jobs") as cursor:
            assert await cursor.fetchone() == (1,)
        async with db.execute("SELECT COUNT(*) FROM history_import_source_records") as cursor:
            assert await cursor.fetchone() == (1,)
        async with db.execute("SELECT COUNT(*) FROM history_import_job_records") as cursor:
            assert await cursor.fetchone() == (1,)


@pytest.mark.asyncio
async def test_delete_forgets_shared_event_only_after_final_active_membership(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    shared = tmp_path / "shared.md"
    changed = tmp_path / "changed.md"
    shared.write_text("# Notes\n\nShared source.", encoding="utf-8")
    changed.write_text("# Notes\n\nFirst version.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    first = await service.preview_markdown_paths([str(shared), str(changed)])
    await service.confirm(
        job_id=first.job_id,
        confirm_personal_writing=True,
        included_source_ids=first.included_source_ids,
    )
    changed.write_text("# Notes\n\nSecond version.", encoding="utf-8")
    second = await service.preview_markdown_paths([str(shared), str(changed)])
    await service.confirm(
        job_id=second.job_id,
        confirm_personal_writing=True,
        included_source_ids=second.included_source_ids,
    )
    first_events = set(await history_store.list_imported_event_ids(job_id=first.job_id))
    second_events = set(await history_store.list_imported_event_ids(job_id=second.job_id))
    shared_event_id = next(iter(first_events & second_events))
    first_only_event_id = next(iter(first_events - second_events))
    second_only_event_id = next(iter(second_events - first_events))

    await service.delete(first.job_id)

    assert memory.forgotten_event_ids == [first_only_event_id]
    assert shared_event_id not in memory.forgotten_event_ids

    await service.delete(second.job_id)

    assert set(memory.forgotten_event_ids) == {
        first_only_event_id,
        shared_event_id,
        second_only_event_id,
    }
    await service.stop()


@pytest.mark.asyncio
async def test_unconfirmed_overlapping_preview_does_not_retain_confirmed_memory(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    shared = tmp_path / "shared.md"
    changed = tmp_path / "changed.md"
    shared.write_text("# Notes\n\nShared source.", encoding="utf-8")
    changed.write_text("# Notes\n\nFirst version.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    first = await service.preview_markdown_paths([str(shared), str(changed)])
    await service.confirm(
        job_id=first.job_id,
        confirm_personal_writing=True,
        included_source_ids=first.included_source_ids,
    )
    first_event_ids = set(await history_store.list_imported_event_ids(job_id=first.job_id))

    changed.write_text("# Notes\n\nSecond version.", encoding="utf-8")
    second = await service.preview_markdown_paths([str(shared), str(changed)])
    assert second.status == "preview_ready"

    await service.delete(first.job_id)

    assert set(memory.forgotten_event_ids) == first_event_ids
    second_preview = await service.get_source_preview(
        job_id=second.job_id,
        source_id="shared.md",
    )
    assert second_preview.records[0].content == "# Notes\n\nShared source."
    async with aiosqlite.connect(history_store.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT DISTINCT source.speaker_role
            FROM history_import_source_records AS source
            JOIN history_import_job_records AS membership
              ON membership.source_record_key = source.source_record_key
            WHERE membership.job_id = ?
            """,
            (second.job_id,),
        ) as cursor:
            roles = {str(row["speaker_role"]) for row in await cursor.fetchall()}
    assert roles == {"unknown"}
    await service.stop()


@pytest.mark.asyncio
async def test_delete_cleans_pending_event_identity_and_mtime_reimport_succeeds(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "journal.md"
    markdown.write_text("# Journal\n\nAn unchanged entry.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    first = await service.preview_markdown_paths([str(markdown)])
    first_records = await history_store.list_source_records(
        job_id=first.job_id,
        source_id="journal.md",
        limit=10,
    )
    await service.delete(first.job_id)

    assert memory.forgotten_event_ids == [first_records[0].event_id]

    markdown.touch()
    second = await service.preview_markdown_paths([str(markdown)])
    second_records = await history_store.list_source_records(
        job_id=second.job_id,
        source_id="journal.md",
        limit=10,
    )

    assert second.job_id != first.job_id
    assert second_records[0].event_id == first_records[0].event_id
    await service.stop()


@pytest.mark.asyncio
async def test_delete_then_explicit_reimport_restores_same_stable_l1_event(
    tmp_path: Path,
) -> None:
    memory_db_path = tmp_path / "memory.db"
    memory = _build_real_memory(tmp_path)
    await memory.initialize()
    store = HistoryImportStore(db_path=str(memory_db_path))
    service = HistoryImportService(store=store, memory=memory)
    markdown = tmp_path / "journal.md"
    markdown.write_text("# Journal\n\nAn unchanged entry.", encoding="utf-8")

    try:
        first = await service.preview_markdown_paths([str(markdown)])
        first_event_id = first.preview_records[0].event_id
        await service.confirm(
            job_id=first.job_id,
            confirm_personal_writing=True,
            included_source_ids=first.included_source_ids,
        )
        await service.delete(first.job_id)

        assert await memory.l1.get_event(first_event_id) is None
        async with aiosqlite.connect(memory_db_path) as db:
            tombstone = await (
                await db.execute(
                    "SELECT 1 FROM memory_source_event_tombstones WHERE event_id = ?",
                    (first_event_id,),
                )
            ).fetchone()
        assert tombstone is None

        second = await service.preview_markdown_paths([str(markdown)])
        assert second.job_id != first.job_id
        assert second.preview_records[0].event_id == first_event_id
        ready = await service.confirm(
            job_id=second.job_id,
            confirm_personal_writing=True,
            included_source_ids=second.included_source_ids,
        )

        assert ready.quick_ready is True
        assert ready.imported_count == 1
        restored = await memory.l1.get_event(first_event_id)
        assert restored is not None
        assert restored["content"] == "# Journal\n\nAn unchanged entry."
    finally:
        await service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_confirm_requires_personal_writing_authorship(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "chat-shaped.md"
    markdown.write_text(
        "- Me: Shared line.\n- Alice: Shared reply.",
        encoding="utf-8",
    )
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    preview = await service.preview_markdown_paths([str(markdown)])

    with pytest.raises(
        HistoryImportValidationError,
        match="personal_writing_confirmation_required",
    ):
        await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=False,
            included_source_ids=preview.included_source_ids,
        )
    await service.stop()


@pytest.mark.asyncio
async def test_personal_markdown_headings_import_as_one_source_event(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "weekly.md"
    markdown.write_text(
        "# 本周记录\n\n"
        "周一重新开始跑步。\n\n"
        "## 最近在听\n\n"
        "反复听同一张专辑。\n\n"
        "## 下周\n\n"
        "想去一次公园。\n",
        encoding="utf-8",
    )
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    preview = await service.preview_markdown_paths([str(markdown)])

    assert preview.detected_kind == "document"
    assert preview.total_records == 1
    assert preview.sources[0].record_count == 1
    assert preview.preview_records[0].content == markdown.read_text(encoding="utf-8").strip()

    ready = await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_source_ids=preview.included_source_ids,
    )

    assert ready.quick_imported_count == 1
    assert len(memory.raw_events) == 1
    event = memory.raw_events[0]
    assert event.content == preview.preview_records[0].content
    assert event.source == "history_import"
    assert event.event_type == "history_import.document"
    assert event.author_type == "user"
    assert event.memory_domain.label == "user_authored"
    assert event.metadata_json["history_import"]["historical"] is True
    assert (
        event.metadata_json["history_import"]["timestamp_confidence"]
        == preview.preview_records[0].timestamp_confidence
    )
    assert event.metadata_json["history_import"]["timestamp_anchor_source"] == (
        preview.preview_records[0].timestamp_anchor_source
    )

    from magi.memory.evidence import classify_event_evidence
    from magi.memory.l2.batch_models import L2BatchEvent, L2EventWindow
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile
    from magi.memory.l2.pipeline.source_time_policy import resolve_event_time_semantics
    from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt

    classification = classify_event_evidence(event)
    profile = resolve_extraction_profile(event)
    batch_event = L2BatchEvent.from_dict(event.to_dict())
    prompt = render_phase1_extract_prompt(
        event_window=L2EventWindow(events=[batch_event]),
        focal_subject={"entity_ref": "user:local-user", "entity_type": "user"},
        extraction_instructions=profile.phase1_instructions,
    )

    assert classification.reason_code == "user_authored_history_archive"
    assert profile.profile_id == "history_import.document"
    assert (
        batch_event.metadata_json["history_import"]["timestamp_confidence"]
        == preview.preview_records[0].timestamp_confidence
    )
    time_semantics = resolve_event_time_semantics(event)
    assert time_semantics.timestamp_confidence == preview.preview_records[0].timestamp_confidence
    assert time_semantics.timestamp_quality == "approximate_recorded"
    assert time_semantics.timestamp_anchor_source == "file_mtime"
    assert prompt.count(event.content) == 1
    assert "historical documents, not live chat turns" in prompt
    await service.stop()


@pytest.mark.asyncio
async def test_quick_context_keeps_long_chat_shaped_markdown_as_one_document(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "long-chat.md"
    lines = [
        (
            f"- Me: Meaningful personal message {index}"
            if index % 20 == 0
            else f"- Alice: Context message {index}"
        )
        for index in range(600)
    ]
    markdown.write_text("\n".join(lines), encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    preview = await service.preview_markdown_paths([str(markdown)])
    assert preview.total_records == 1
    await history_store.set_scope(
        job_id=preview.job_id,
        self_participant_ids=["__document_author__"],
        included_source_ids=preview.included_source_ids,
    )
    selected = await history_store.select_quick_records(job_id=preview.job_id)

    assert len(selected) == 1
    assert selected[0].session_seq == 0
    assert selected[0].content == markdown.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_document_pending_work_remains_ordered_by_event_time(
    history_store: HistoryImportStore,
) -> None:
    job = HistoryImportJob(
        job_id="document-order-job",
        source_type="markdown",
        source_fingerprint="document-order-fingerprint",
        source_ids=["newer-document", "older-document"],
        included_source_ids=["newer-document", "older-document"],
        detected_kind="document",
        status="preview_ready",
        total_records=2,
        meaningful_records=2,
        quick_target_records=200,
        quick_max_records=500,
        quick_imported_count=0,
        imported_count=0,
        projected_count=0,
        self_participant_ids=["__document_author__"],
        warnings=[],
        quick_ready=False,
        created_at=1.0,
        updated_at=1.0,
    )

    def record(
        *,
        job_record_id: str,
        source_id: str,
        session_id: str,
        event_at: float,
    ) -> HistoryImportRecord:
        return HistoryImportRecord(
            job_record_id=job_record_id,
            job_id=job.job_id,
            source_record_key=f"source-{job_record_id}",
            file_fingerprint=f"fingerprint-{job_record_id}",
            source_id=source_id,
            source_name=f"{source_id}.md",
            source_kind="document",
            parsed_session_key=source_id,
            session_id=session_id,
            session_seq=0,
            speaker_id="__document_author__",
            speaker_name="Document author",
            speaker_role="user",
            message_key="document",
            parent_message_key=None,
            content=source_id,
            event_at=event_at,
            timestamp_confidence="exact",
            timestamp_anchor_source="source_timestamp",
            calendar_timezone_id="Asia/Shanghai",
            meaningful=True,
            event_id=f"event-{job_record_id}",
            created_at=1.0,
            updated_at=1.0,
        )

    records = [
        record(
            job_record_id="newer",
            source_id="newer-document",
            session_id="history_a",
            event_at=20.0,
        ),
        record(
            job_record_id="older",
            source_id="older-document",
            session_id="history_z",
            event_at=10.0,
        ),
    ]
    await history_store.create_preview(job=job, records=records)

    pending_raw = await history_store.list_pending_raw_records(job_id=job.job_id, limit=10)
    for item in records:
        await history_store.mark_raw_stored(
            job_id=job.job_id,
            job_record_id=item.job_record_id,
            quick=False,
        )
    pending_projection = await history_store.list_pending_projection_records(
        job_id=job.job_id,
        limit=10,
    )

    assert [item.event_at for item in pending_raw] == [10.0, 20.0]
    assert [item.event_at for item in pending_projection] == [10.0, 20.0]


@pytest.mark.asyncio
async def test_confirm_writes_previewed_markdown_into_the_real_l1_store(
    tmp_path: Path,
) -> None:
    memory_db_path = tmp_path / "memory.db"
    memory = _build_real_memory(tmp_path)
    await memory.initialize()
    service = HistoryImportService(
        store=HistoryImportStore(db_path=str(memory_db_path)),
        memory=memory,
    )
    markdown = tmp_path / "personal-notes.md"
    markdown.write_text(
        "- Me: I started learning pottery.\n"
        "- Alice: What do you enjoy about it?\n"
        "- Me: It helps me slow down.\n",
        encoding="utf-8",
    )

    try:
        preview = await service.preview_markdown_paths([str(markdown)])
        ready = await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )

        assert ready.quick_ready is True
        stored = [await memory.l1.get_event(record.event_id) for record in preview.preview_records]
        assert all(item is not None for item in stored)
        assert [item["content"] for item in stored if item is not None] == [
            record.content for record in preview.preview_records
        ]
        assert [item["author_type"] for item in stored if item is not None] == ["user"]
    finally:
        await service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_quick_retry_after_l1_write_does_not_duplicate_the_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_db_path = tmp_path / "memory.db"
    memory = _build_real_memory(tmp_path)
    await memory.initialize()
    store = HistoryImportStore(db_path=str(memory_db_path))
    service = HistoryImportService(store=store, memory=memory)
    markdown = tmp_path / "personal-notes.md"
    markdown.write_text("I started learning pottery.", encoding="utf-8")
    original_mark_raw_stored = store.mark_raw_stored
    fail_once = True

    async def interrupted_mark_raw_stored(*args: Any, **kwargs: Any) -> None:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise InterruptedError("simulated process interruption")
        await original_mark_raw_stored(*args, **kwargs)

    monkeypatch.setattr(store, "mark_raw_stored", interrupted_mark_raw_stored)

    try:
        preview = await service.preview_markdown_paths([str(markdown)])
        failed = await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )

        assert failed.status == "failed"
        assert failed.quick_ready is False
        assert await memory.l1.count_events(source_filters=["history_import"]) == 1

        resumed = await service.resume(preview.job_id)
        assert resumed.status == "running"
        await _wait_for_completed_job(service, preview.job_id)

        assert await memory.l1.count_events(source_filters=["history_import"]) == 1
        stored = await memory.l1.get_event(preview.preview_records[0].event_id)
        assert stored is not None
        assert stored["content"] == "I started learning pottery."
    finally:
        await service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_diagnostics_trace_import_and_detect_a_missing_l1_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()
    monkeypatch.setattr(history_import_service_module, "logger", logger)
    memory_db_path = tmp_path / "memory.db"
    memory = _build_real_memory(tmp_path)
    await memory.initialize()
    store = HistoryImportStore(db_path=str(memory_db_path))
    service = HistoryImportService(store=store, memory=memory)
    markdown = tmp_path / "private-diary.md"
    private_content = "I took the quiet route home and listened to a private demo."
    markdown.write_text(private_content, encoding="utf-8")

    restarted_service: HistoryImportService | None = None
    try:
        await service.start()
        preview = await service.preview_markdown_paths([str(markdown)])
        await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )
        await _wait_for_completed_job(service, preview.job_id)

        checkpoint_calls = [
            call
            for call in logger.info.call_args_list
            if call.args and call.args[0] == "History import checkpoint"
        ]
        checkpoints = {call.kwargs["checkpoint"]: call.kwargs for call in checkpoint_calls}
        assert checkpoints["quick_ready"]["imported_count"] == 1
        assert checkpoints["quick_ready"]["l1_history_event_count"] == 1
        assert checkpoints["completed"]["projected_count"] == 0
        assert private_content not in repr(logger.method_calls)
        assert markdown.name not in repr(logger.method_calls)

        await service.stop()
        await memory.l1.clear(restart_workers=False)
        logger.reset_mock()

        restarted_service = HistoryImportService(store=store, memory=memory)
        await restarted_service.start()

        mismatch_calls = [
            call
            for call in logger.warning.call_args_list
            if call.args and call.args[0] == "History import integrity audit"
        ]
        assert len(mismatch_calls) == 1
        assert mismatch_calls[0].kwargs["checkpoint"] == "startup"
        assert mismatch_calls[0].kwargs["ledger_imported_count"] == 1
        assert mismatch_calls[0].kwargs["l1_history_event_count"] == 0
        assert mismatch_calls[0].kwargs["consistent"] is False
        assert private_content not in repr(logger.method_calls)
        assert markdown.name not in repr(logger.method_calls)
    finally:
        if restarted_service is not None:
            await restarted_service.stop()
        else:
            await service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_full_clear_waits_for_inflight_preview_and_removes_its_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = _build_real_memory(tmp_path)
    await memory.initialize()
    store = HistoryImportStore(db_path=str(tmp_path / "memory.db"))
    service = HistoryImportService(store=store, memory=memory)
    markdown = tmp_path / "preview-during-clear.md"
    markdown.write_text("# Private notes\n\nA detail that must be cleared.", encoding="utf-8")
    preview_reached_store = asyncio.Event()
    release_preview = asyncio.Event()
    original_find = store.find_active_by_fingerprint

    async def delayed_find(fingerprint: str):
        preview_reached_store.set()
        await release_preview.wait()
        return await original_find(fingerprint)

    monkeypatch.setattr(store, "find_active_by_fingerprint", delayed_find)
    preview_task: asyncio.Task[Any] | None = None
    clear_task: asyncio.Task[Any] | None = None
    try:
        preview_task = asyncio.create_task(service.preview_markdown_paths([str(markdown)]))
        await asyncio.wait_for(preview_reached_store.wait(), timeout=1)

        clear_task = asyncio.create_task(
            memory.clear_all_memory(
                user_content_clear_boundaries=(service.user_content_clear_boundary,),
            )
        )

        async def wait_for_clear_request() -> None:
            while not memory.memory_clear_in_progress():
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_clear_request(), timeout=1)
        assert clear_task.done() is False

        release_preview.set()
        preview = await asyncio.wait_for(preview_task, timeout=2)
        await asyncio.wait_for(clear_task, timeout=5)

        assert await store.get_job(preview.job_id) is None
        assert await store.list_active_jobs() == []
        assert service._quick_tasks == {}
        assert service._tasks == {}
        assert service._locks == {}
    finally:
        release_preview.set()
        pending = [
            task for task in (preview_task, clear_task) if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_full_clear_cancels_import_workers_before_shared_table_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.memory import store_lifecycle

    memory = _build_real_memory(tmp_path)
    await memory.initialize()
    service = HistoryImportService(
        store=HistoryImportStore(db_path=str(tmp_path / "memory.db")),
        memory=memory,
    )
    worker_started = asyncio.Event()
    worker_finished = asyncio.Event()

    async def pending_worker(_job_id: str) -> None:
        worker_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            worker_finished.set()

    monkeypatch.setattr(service, "_run_background", pending_worker)
    original_clear_shared = store_lifecycle.clear_shared_auxiliary_memory

    async def observed_clear_shared(*args: Any, **kwargs: Any):
        assert worker_finished.is_set()
        return await original_clear_shared(*args, **kwargs)

    monkeypatch.setattr(
        store_lifecycle,
        "clear_shared_auxiliary_memory",
        observed_clear_shared,
    )
    service._start_background("pending-job")
    await asyncio.wait_for(worker_started.wait(), timeout=1)

    try:
        await asyncio.wait_for(
            memory.clear_all_memory(
                user_content_clear_boundaries=(service.user_content_clear_boundary,),
            ),
            timeout=5,
        )

        assert worker_finished.is_set()
        assert service._quick_tasks == {}
        assert service._tasks == {}
        assert service._locks == {}
    finally:
        await service.stop()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_clear_does_not_deadlock_between_worker_and_selection_lock_order(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "lock-order.md"
    markdown.write_text("# Notes\n\nA private detail.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)
    preview = await service.preview_markdown_paths([str(markdown)])
    first_holder_ready = asyncio.Event()
    release_first_holder = asyncio.Event()
    second_waiter_ready = asyncio.Event()

    class _PauseFirstJobLock:
        def __init__(self) -> None:
            self._lock = asyncio.Lock()
            self._attempts = 0

        async def __aenter__(self):
            self._attempts += 1
            if self._attempts == 2:
                second_waiter_ready.set()
            await self._lock.acquire()
            if self._attempts == 1:
                first_holder_ready.set()
                await release_first_holder.wait()
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            _ = (exc_type, exc, traceback)
            self._lock.release()

    service._locks[preview.job_id] = _PauseFirstJobLock()  # type: ignore[assignment]
    service._start_background(preview.job_id)
    await asyncio.wait_for(first_holder_ready.wait(), timeout=1)
    selection_task = asyncio.create_task(
        service.update_selection(
            job_id=preview.job_id,
            included_source_ids=preview.included_source_ids,
        )
    )
    await asyncio.wait_for(second_waiter_ready.wait(), timeout=1)

    async def clear_service() -> None:
        async with memory.operation_barrier.exclusive():
            async with service.user_content_clear_boundary():
                return

    clear_task = asyncio.create_task(clear_service())

    async def wait_for_exclusive_waiter() -> None:
        while memory.operation_barrier._exclusive_waiters == 0:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_exclusive_waiter(), timeout=1)

    try:
        release_first_holder.set()
        with pytest.raises(
            HistoryImportValidationError,
            match="history_import_selection_locked",
        ):
            await asyncio.wait_for(selection_task, timeout=2)
        await asyncio.wait_for(clear_task, timeout=2)

        assert service._quick_tasks == {}
        assert service._tasks == {}
        assert service._locks == {}
    finally:
        release_first_holder.set()
        pending = [task for task in (selection_task, clear_task) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await service.stop()


@pytest.mark.asyncio
async def test_selection_excludes_unwanted_files_before_any_memory_write(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    journal = tmp_path / "journal.md"
    clipping = tmp_path / "clipping.md"
    journal.write_text("# Journal\n\nI started learning pottery.", encoding="utf-8")
    clipping.write_text("# Saved article\n\nSomeone else's long essay.", encoding="utf-8")
    memory = _MemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)

    preview = await service.preview_markdown_paths([str(journal), str(clipping)])
    selected = await service.update_selection(
        job_id=preview.job_id,
        included_source_ids=["journal.md"],
    )

    assert selected.included_source_ids == ["journal.md"]
    assert {source.source_name: source.included for source in selected.sources} == {
        "clipping.md": False,
        "journal.md": True,
    }

    ready = await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_source_ids=["journal.md"],
    )
    assert ready.total_records == 1
    assert [event.content for event in memory.raw_events] == [
        "# Journal\n\nI started learning pottery."
    ]
    await service.stop()


@pytest.mark.asyncio
async def test_append_markdown_preserves_selection_and_skips_duplicates(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("First private note.", encoding="utf-8")
    second.write_text("Second private note.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    preview = await service.preview_markdown_paths([str(first)])
    await service.update_selection(job_id=preview.job_id, included_source_ids=[])
    result = await service.append_markdown_paths(
        job_id=preview.job_id,
        paths=[str(first), str(second)],
    )

    assert result.added_source_count == 1
    assert result.duplicate_source_count == 1
    assert result.job.source_ids == ["first.md", "second.md"]
    assert result.job.included_source_ids == ["second.md"]
    assert result.job.total_records == 2
    assert {source.source_name: source.included for source in result.job.sources} == {
        "first.md": False,
        "second.md": True,
    }
    await service.stop()


@pytest.mark.asyncio
async def test_append_markdown_rejects_changed_content_with_the_same_source_name(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    first = first_directory / "notes.md"
    conflicting = second_directory / "notes.md"
    first.write_text("Original private note.", encoding="utf-8")
    conflicting.write_text("Different private note.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())
    preview = await service.preview_markdown_paths([str(first)])

    with pytest.raises(
        HistoryImportValidationError,
        match="history_import_source_name_conflict",
    ):
        await service.append_markdown_paths(
            job_id=preview.job_id,
            paths=[str(conflicting)],
        )
    current = await service.get_job(preview.job_id)
    assert current.source_ids == ["notes.md"]
    assert current.total_records == 1
    await service.stop()


@pytest.mark.asyncio
async def test_append_markdown_is_locked_after_scope_confirmation(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("First private note.", encoding="utf-8")
    second.write_text("Second private note.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())
    preview = await service.preview_markdown_paths([str(first)])
    await history_store.set_scope(
        job_id=preview.job_id,
        self_participant_ids=["__document_author__"],
        included_source_ids=preview.included_source_ids,
    )

    with pytest.raises(
        HistoryImportValidationError,
        match="history_import_selection_locked",
    ):
        await service.append_markdown_paths(
            job_id=preview.job_id,
            paths=[str(second)],
        )
    await service.stop()


@pytest.mark.asyncio
async def test_committed_scope_freezes_selection_and_is_payload_idempotent(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    first_file = tmp_path / "first.md"
    second_file = tmp_path / "second.md"
    first_file.write_text("First entry.", encoding="utf-8")
    second_file.write_text("Second entry.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())
    preview = await service.preview_markdown_paths([str(first_file), str(second_file)])

    committed = await history_store.set_scope(
        job_id=preview.job_id,
        self_participant_ids=["__document_author__"],
        included_source_ids=["first.md"],
    )
    repeated = await history_store.set_scope(
        job_id=preview.job_id,
        self_participant_ids=["__document_author__"],
        included_source_ids=["first.md"],
    )

    assert committed.included_source_ids == ["first.md"]
    assert repeated.included_source_ids == ["first.md"]
    with pytest.raises(ValueError, match="history_import_scope_conflict"):
        await history_store.set_scope(
            job_id=preview.job_id,
            self_participant_ids=["__document_author__"],
            included_source_ids=["second.md"],
        )
    with pytest.raises(
        HistoryImportValidationError,
        match="history_import_selection_locked",
    ):
        await service.update_selection(
            job_id=preview.job_id,
            included_source_ids=["second.md"],
        )
    current = await history_store.get_job_progress(preview.job_id)
    assert current is not None
    assert current.included_source_ids == ["first.md"]
    await service.stop()


@pytest.mark.asyncio
async def test_concurrent_confirmation_reuses_only_the_same_payload(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "journal.md"
    markdown.write_text("A quiet morning.", encoding="utf-8")
    memory = _PausedRawMemoryStub()
    service = HistoryImportService(store=history_store, memory=memory)
    preview = await service.preview_markdown_paths([str(markdown)])
    first = asyncio.create_task(
        service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=preview.included_source_ids,
        )
    )

    try:
        await asyncio.wait_for(memory.raw_write_started.wait(), timeout=1)
        repeated = asyncio.create_task(
            service.confirm(
                job_id=preview.job_id,
                confirm_personal_writing=True,
                included_source_ids=list(reversed(preview.included_source_ids)),
            )
        )
        await asyncio.sleep(0)
        with pytest.raises(
            HistoryImportValidationError,
            match="history_import_confirmation_conflict",
        ):
            await service.confirm(
                job_id=preview.job_id,
                confirm_personal_writing=False,
                included_source_ids=preview.included_source_ids,
            )

        memory.release_raw_write.set()
        first_result, repeated_result = await asyncio.gather(first, repeated)
        assert first_result.job_id == repeated_result.job_id == preview.job_id
        assert len(memory.raw_events) == 1
    finally:
        memory.release_raw_write.set()
        await asyncio.gather(first, return_exceptions=True)
        await service.stop()


@pytest.mark.asyncio
async def test_preview_selection_can_be_empty_but_confirmation_cannot(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "journal.md"
    markdown.write_text("# Journal\n\nA quiet morning.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    preview = await service.preview_markdown_paths([str(markdown)])
    empty = await service.update_selection(
        job_id=preview.job_id,
        included_source_ids=[],
    )

    assert empty.included_source_ids == []
    assert empty.sources[0].included is False
    with pytest.raises(
        HistoryImportValidationError,
        match="history_import_selection_empty",
    ):
        await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_source_ids=[],
        )


@pytest.mark.asyncio
async def test_source_preview_returns_bounded_content_for_one_file(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "long-journal.md"
    markdown.write_text("A" * (SOURCE_PREVIEW_MAX_CHARS + 500), encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    job = await service.preview_markdown_paths([str(markdown)])
    preview = await service.get_source_preview(
        job_id=job.job_id,
        source_id="long-journal.md",
    )

    assert preview.source_name == "long-journal.md"
    assert preview.detected_kind == "document"
    assert len(preview.records) == 1
    assert len(preview.records[0].content) == SOURCE_PREVIEW_MAX_CHARS
    assert preview.truncated is True


@pytest.mark.asyncio
async def test_first_contact_snippet_uses_only_confirmed_user_writing(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "journal.md"
    markdown.write_text(
        "# Pottery notes\n\n"
        "I keep returning to this pottery class.\n\n"
        "Working with clay helps me slow down.\n",
        encoding="utf-8",
    )
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    preview = await service.preview_markdown_paths([str(markdown)])
    await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_source_ids=preview.included_source_ids,
    )

    snippet = await service.get_first_contact_snippet()

    assert snippet is not None
    assert "pottery class" in snippet
    assert "Working with clay" in snippet
    await service.stop()
