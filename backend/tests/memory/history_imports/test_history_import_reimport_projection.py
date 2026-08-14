"""Regression coverage for history-import delete and explicit re-import."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.history_imports.models import HistoryImportJob
from magi.memory.history_imports.service import HistoryImportService
from magi.memory.history_imports.store import HistoryImportStore


def _build_memory(tmp_path: Path) -> UnifiedMemoryStore:
    return UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        archive_dir_path=str(tmp_path / "archive"),
        enable_l0=False,
        enable_l2=True,
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


async def _projection_job(db_path: Path, event_id: str) -> aiosqlite.Row | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT status, attempt_count, completed_at, last_error
            FROM l2_projection_jobs
            WHERE event_id = ?
            """,
            (event_id,),
        ) as cursor:
            return await cursor.fetchone()


async def _wait_for_completed_job(
    service: HistoryImportService,
    job_id: str,
) -> HistoryImportJob:
    for _ in range(100):
        job = await service.get_job(job_id)
        if job.status == "completed" and job_id not in service._tasks:
            return job
        await asyncio.sleep(0.01)
    pytest.fail("History import did not complete")


@pytest.mark.asyncio
async def test_delete_then_reimport_requeues_same_stable_event_for_l2(
    tmp_path: Path,
) -> None:
    memory_db_path = tmp_path / "memory.db"
    memory = _build_memory(tmp_path)
    await memory.initialize(start_workers=False)
    store = HistoryImportStore(db_path=str(memory_db_path))
    service = HistoryImportService(store=store, memory=memory)
    markdown = tmp_path / "journal.md"
    markdown.write_text(
        "# Journal\n\nI really enjoy long-distance hiking on weekends.",
        encoding="utf-8",
    )

    try:
        first = await service.preview_markdown_paths([str(markdown)])
        event_id = first.preview_records[0].event_id
        await service.confirm(
            job_id=first.job_id,
            confirm_personal_writing=True,
            included_source_ids=first.included_source_ids,
        )
        first_ready = await _wait_for_completed_job(service, first.job_id)

        assert first_ready.projected_count == 1
        first_projection = await _projection_job(memory_db_path, event_id)
        assert first_projection is not None
        assert first_projection["status"] == "pending"

        await service.delete(first.job_id)

        assert await memory.l1.get_event(event_id) is None
        assert await _projection_job(memory_db_path, event_id) is None

        second = await service.preview_markdown_paths([str(markdown)])
        assert second.job_id != first.job_id
        assert second.preview_records[0].event_id == event_id
        await service.confirm(
            job_id=second.job_id,
            confirm_personal_writing=True,
            included_source_ids=second.included_source_ids,
        )
        second_ready = await _wait_for_completed_job(service, second.job_id)

        assert second_ready.quick_ready is True
        assert second_ready.imported_count == 1
        assert second_ready.projected_count == 1
        second_projection = await _projection_job(memory_db_path, event_id)
        assert second_projection is not None
        assert second_projection["status"] == "pending"
        assert second_projection["attempt_count"] == 0
        assert second_projection["completed_at"] is None
        assert second_projection["last_error"] is None
        assert await memory.l1.get_event(event_id) is not None
    finally:
        await service.stop()
        await memory.shutdown()
