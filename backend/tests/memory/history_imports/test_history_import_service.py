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
from magi.core.operation_barrier import AsyncOperationBarrier
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports import service as history_import_service_module
from magi.memory.history_imports.service import (
    SOURCE_PREVIEW_MAX_CHARS,
    HistoryImportService,
    HistoryImportValidationError,
)
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

    async def forget_known_source_events(
        self,
        event_ids,
        *,
        reason,
        block_source_item,
    ):
        self.forgotten_event_ids.extend(event_ids)


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
        for statement in CREATE_STATEMENTS:
            await db.execute(statement)
        await db.executescript(SELECTION_SCHEMA_SQL)
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
    assert {item.name for item in preview.participants} == {"__document_author__"}

    ready = await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_files=preview.included_files,
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
    assert first_event.metadata_json["history_import"]["timestamp_anchor_source"] == (
        "file_mtime"
    )
    assert first_event.metadata_json["_temporal"]["calendar_timezone_id"] == (
        "Asia/Shanghai"
    )

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
            included_files=preview.included_files,
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
            included_files=preview.included_files,
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
            included_files=preview.included_files,
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

    assert len(preview.source_files) == 2
    assert len(set(preview.source_files)) == 2
    assert all(str(tmp_path) not in source_name for source_name in preview.source_files)


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
        included_files=preview.included_files,
    )
    await service.delete(preview.job_id)

    deleted = await service.get_job(preview.job_id)
    assert deleted.status == "deleted"
    assert memory.forgotten_event_ids == [memory.raw_events[0].event_id]
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
            source_name="unchanged.md",
            limit=10,
        )
    )[0]
    first_changed = (
        await history_store.list_source_records(
            job_id=first.job_id,
            source_name="changed.md",
            limit=10,
        )
    )[0]

    changed.write_text("# Notes\n\nSecond version.", encoding="utf-8")
    second = await service.preview_markdown_paths([str(unchanged), str(changed)])
    second_unchanged = (
        await history_store.list_source_records(
            job_id=second.job_id,
            source_name="unchanged.md",
            limit=10,
        )
    )[0]
    second_changed = (
        await history_store.list_source_records(
            job_id=second.job_id,
            source_name="changed.md",
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
            await (
                await db.execute("SELECT COUNT(*) FROM history_import_job_records")
            ).fetchone()
        )[0]
    assert source_count == 3
    assert membership_count == 4


@pytest.mark.asyncio
async def test_identical_file_selection_reuses_existing_job(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "notes.md"
    markdown.write_text("# Notes\n\nStable content.", encoding="utf-8")
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    first = await service.preview_markdown_paths([str(markdown)])
    second = await service.preview_markdown_paths([str(markdown)])

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
        included_files=first.included_files,
    )
    changed.write_text("# Notes\n\nSecond version.", encoding="utf-8")
    second = await service.preview_markdown_paths([str(shared), str(changed)])
    await service.confirm(
        job_id=second.job_id,
        confirm_personal_writing=True,
        included_files=second.included_files,
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
            included_files=preview.included_files,
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
    assert preview.preview_records[0].content == markdown.read_text(
        encoding="utf-8"
    ).strip()

    ready = await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_files=preview.included_files,
    )

    assert ready.quick_imported_count == 1
    assert len(memory.raw_events) == 1
    event = memory.raw_events[0]
    assert event.content == preview.preview_records[0].content
    assert event.source == "history_import_markdown"
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

    assert classification.reason_code == "user_authored_history_document"
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
        self_participants=["__document_author__"],
        included_files=preview.included_files,
    )
    selected = await history_store.select_quick_records(job_id=preview.job_id)

    assert len(selected) == 1
    assert selected[0].session_seq == 0
    assert selected[0].content == markdown.read_text(encoding="utf-8")


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
            included_files=preview.included_files,
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
            included_files=preview.included_files,
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
        preview_task = asyncio.create_task(
            service.preview_markdown_paths([str(markdown)])
        )
        await asyncio.wait_for(preview_reached_store.wait(), timeout=1)

        clear_task = asyncio.create_task(
            memory.clear_all_memory(
                user_content_clear_boundaries=(
                    service.user_content_clear_boundary,
                ),
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
        assert service._tasks == {}
        assert service._locks == {}
    finally:
        release_preview.set()
        pending = [
            task
            for task in (preview_task, clear_task)
            if task is not None and not task.done()
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
                user_content_clear_boundaries=(
                    service.user_content_clear_boundary,
                ),
            ),
            timeout=5,
        )

        assert worker_finished.is_set()
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
            included_files=preview.included_files,
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
        await asyncio.wait_for(selection_task, timeout=2)
        await asyncio.wait_for(clear_task, timeout=2)

        assert service._tasks == {}
        assert service._locks == {}
    finally:
        release_first_holder.set()
        pending = [
            task
            for task in (selection_task, clear_task)
            if not task.done()
        ]
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
        included_files=["journal.md"],
    )

    assert selected.included_files == ["journal.md"]
    assert {source.source_name: source.included for source in selected.sources} == {
        "clipping.md": False,
        "journal.md": True,
    }

    ready = await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=True,
        included_files=["journal.md"],
    )
    assert ready.total_records == 1
    assert [event.content for event in memory.raw_events] == [
        "# Journal\n\nI started learning pottery."
    ]
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
        included_files=[],
    )

    assert empty.included_files == []
    assert empty.sources[0].included is False
    with pytest.raises(
        HistoryImportValidationError,
        match="history_import_selection_empty",
    ):
        await service.confirm(
            job_id=preview.job_id,
            confirm_personal_writing=True,
            included_files=[],
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
        source_name="long-journal.md",
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
        included_files=preview.included_files,
    )

    snippet = await service.get_first_contact_snippet()

    assert snippet is not None
    assert "pottery class" in snippet
    assert "Working with clay" in snippet
    await service.stop()
