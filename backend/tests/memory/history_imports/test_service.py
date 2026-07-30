from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from magi.db.migrations.memory_shared.versions.v36_history_imports import (
    CREATE_STATEMENTS,
)
from magi.db.migrations.memory_shared.versions.v37_history_import_selection import (
    SCHEMA_SQL as SELECTION_SCHEMA_SQL,
)
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports.service import HistoryImportService
from magi.memory.history_imports.store import HistoryImportStore


class _MemoryStub:
    def __init__(self) -> None:
        self.epoch = 0
        self.raw_events: list[Any] = []
        self.projected_events: list[Any] = []
        self.forgotten_event_ids: list[str] = []

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


@pytest.fixture
async def history_store(tmp_path: Path) -> HistoryImportStore:
    db_path = tmp_path / "memory.db"
    async with aiosqlite.connect(db_path) as db:
        for statement in CREATE_STATEMENTS:
            await db.execute(statement)
        await db.executescript(SELECTION_SCHEMA_SQL)
        await db.commit()
    return HistoryImportStore(db_path=str(db_path))


@pytest.mark.asyncio
async def test_confirm_prepares_recent_context_then_projects_user_turns_in_order(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
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
    assert preview.detected_kind == "chat"
    assert {item.name for item in preview.participants} == {"Me", "Alice"}

    ready = await service.confirm(
        job_id=preview.job_id,
        self_participants=["Me"],
        confirm_personal_writing=False,
        included_files=preview.included_files,
    )
    assert ready.quick_ready is True
    assert ready.quick_imported_count == 4

    for _ in range(50):
        current = await service.get_job(preview.job_id)
        if current.status == "completed":
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("History import did not complete")

    assert [event.content for event in memory.projected_events] == [
        "I started learning pottery.",
        "It helps me slow down.",
    ]
    assert all(
        earlier.session_seq < later.session_seq
        for earlier, later in zip(
            memory.projected_events,
            memory.projected_events[1:],
        )
    )
    assert [event.content for event in memory.raw_events] == [
        "I started learning pottery.",
        "What do you like about it?",
        "It helps me slow down.",
        "That sounds peaceful.",
    ]
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
        self_participants=[],
        confirm_personal_writing=True,
        included_files=preview.included_files,
    )
    await service.delete(preview.job_id)

    deleted = await service.get_job(preview.job_id)
    assert deleted.status == "deleted"
    assert memory.forgotten_event_ids == [memory.raw_events[0].event_id]
    await service.stop()


@pytest.mark.asyncio
async def test_quick_context_expands_but_stops_at_the_bounded_maximum(
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
    await history_store.set_scope(
        job_id=preview.job_id,
        self_participants=["Me"],
        included_files=preview.included_files,
    )
    selected = await history_store.select_quick_records(job_id=preview.job_id)

    assert len(selected) == 500
    assert selected[0].session_seq == 100
    assert selected[-1].session_seq == 599
    assert [item.session_seq for item in selected] == sorted(item.session_seq for item in selected)


@pytest.mark.asyncio
async def test_confirm_writes_previewed_markdown_into_the_real_l1_store(
    tmp_path: Path,
) -> None:
    memory_db_path = tmp_path / "memory.db"
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db_path),
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
            enable_l2_conflict_arbitration=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    service = HistoryImportService(
        store=HistoryImportStore(db_path=str(memory_db_path)),
        memory=memory,
    )
    markdown = tmp_path / "real-chat.md"
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
            self_participants=["Me"],
            confirm_personal_writing=False,
            included_files=preview.included_files,
        )

        assert ready.quick_ready is True
        stored = [await memory.l1.get_event(record.event_id) for record in preview.preview_records]
        assert all(item is not None for item in stored)
        assert [item["content"] for item in stored if item is not None] == [
            record.content for record in preview.preview_records
        ]
        assert [item["author_type"] for item in stored if item is not None] == [
            "user",
            "external",
            "user",
        ]
    finally:
        await service.stop()
        await memory.shutdown()


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
        self_participants=[],
        confirm_personal_writing=True,
        included_files=["journal.md"],
    )
    assert ready.total_records == 1
    assert [event.content for event in memory.raw_events] == [
        "# Journal\n\nI started learning pottery."
    ]
    await service.stop()


@pytest.mark.asyncio
async def test_first_contact_snippet_uses_only_confirmed_user_writing(
    tmp_path: Path,
    history_store: HistoryImportStore,
) -> None:
    markdown = tmp_path / "chat.md"
    markdown.write_text(
        "- Me: I keep returning to this pottery class.\n"
        "- Alice: You should make another bowl.\n"
        "- Me: Working with clay helps me slow down.\n",
        encoding="utf-8",
    )
    service = HistoryImportService(store=history_store, memory=_MemoryStub())

    preview = await service.preview_markdown_paths([str(markdown)])
    await service.confirm(
        job_id=preview.job_id,
        self_participants=["Me"],
        confirm_personal_writing=False,
        included_files=preview.included_files,
    )

    snippet = await service.get_first_contact_snippet()

    assert snippet is not None
    assert "pottery class" in snippet
    assert "Working with clay" in snippet
    assert "make another bowl" not in snippet
    await service.stop()
