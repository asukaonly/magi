from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import threading
import time

import aiosqlite
import pytest

from magi.db.migrations.memory_shared.versions.v58_history_import_source_roles import (
    SCHEMA_SQL as SOURCE_ROLE_SCHEMA_SQL,
)

from magi.db.migrations.memory_shared.versions.v36_history_imports import CREATE_STATEMENTS
from magi.db.migrations.memory_shared.versions.v37_history_import_selection import (
    SCHEMA_SQL as SELECTION_SCHEMA_SQL,
)
from magi.db.migrations.memory_shared.versions.v46_history_import_adapters import (
    SCHEMA_SQL as IMPORTER_SCHEMA_SQL,
)
from magi.core.operation_barrier import AsyncOperationBarrier
from magi.memory.history_imports import service as history_import_service_module
from magi.memory.history_imports.service import (
    HistoryImportService,
    HistoryImportValidationError,
)
from magi.memory.history_imports.models import HistoryImportJob
from magi.memory.history_imports.store import HistoryImportStore
from magi.plugins.history_importers import HistoryImporterRegistry
from magi_plugin_sdk import (
    HistoryImportParseResult,
    HistoryImportRecord,
    HistoryImportSource,
    HistoryImporterSpec,
)
from magi_plugin_sdk.history_imports import MAX_HISTORY_IMPORT_CONTENT_LENGTH


class _Memory:
    def __init__(self) -> None:
        self.epoch = 0
        self.operation_barrier = AsyncOperationBarrier()
        self.raw_events = []
        self.projected_events = []

    def memory_operation_guard(self):
        return self.operation_barrier.operation()

    def memory_operation_epoch(self) -> int:
        return self.epoch

    @asynccontextmanager
    async def governed_l1_write_guard(self):
        yield

    async def store_governed_l1_event_under_write_lock(self, event):  # type: ignore[no-untyped-def]
        self.raw_events.append(event)
        return event.event_id

    async def ingest_event(self, event, *, expected_epoch=None):  # type: ignore[no-untyped-def]
        self.projected_events.append(event)
        return {"event_id": event.event_id, "l2_job_enqueued": True}

    async def forget_known_source_events(self, event_ids, **kwargs):  # type: ignore[no-untyped-def]
        return None


class _ArchiveImporter:
    def __init__(self) -> None:
        self.include_new_message = False
        self.prepend_old_message = False
        self.include_second_source = False
        self.change_first_message = False
        self.change_first_timestamp = False
        self.source_name = "Pottery"
        self.user_display_name = "You"

    async def parse(self, paths):  # type: ignore[no-untyped-def]
        records = [
            HistoryImportRecord(
                message_key="m1",
                source_order=0,
                speaker_id="human",
                speaker_name=self.user_display_name,
                role_hint="user",
                content=(
                    "Why did this message change?"
                    if self.change_first_message
                    else "Why do I keep returning to pottery?"
                ),
                occurred_at=(1_700_000_010.0 if self.change_first_timestamp else 1_700_000_000.0),
                timestamp_confidence="exact",
            ),
            HistoryImportRecord(
                message_key="m2",
                parent_message_key="m1",
                source_order=1,
                speaker_id="assistant",
                speaker_name="Assistant",
                role_hint="assistant",
                content="Perhaps it helps you slow down.",
                occurred_at=1_700_000_001.0,
                timestamp_confidence="exact",
            ),
        ]
        if self.prepend_old_message:
            records.insert(
                0,
                HistoryImportRecord(
                    message_key="m0",
                    source_order=0,
                    speaker_id="human",
                    speaker_name=self.user_display_name,
                    role_hint="user",
                    content="I first noticed pottery at school.",
                    occurred_at=1_699_999_999.0,
                    timestamp_confidence="exact",
                ),
            )
            records[1] = records[1].model_copy(update={"source_order": 1})
            records[2] = records[2].model_copy(update={"source_order": 2})
        if self.include_new_message:
            records.append(
                HistoryImportRecord(
                    message_key="m3",
                    parent_message_key="m2",
                    source_order=2,
                    speaker_id="human",
                    speaker_name=self.user_display_name,
                    role_hint="user",
                    content="It does help me slow down.",
                    timestamp_confidence="unknown",
                )
            )
        sources = [
            HistoryImportSource(
                source_id="conversation-1",
                source_name=self.source_name,
                session_key="shared-session-key",
                records=records,
            )
        ]
        if self.include_second_source:
            sources.append(
                HistoryImportSource(
                    source_id="conversation-2",
                    source_name="Gardening",
                    session_key="shared-session-key",
                    records=[
                        HistoryImportRecord(
                            message_key="m1",
                            source_order=0,
                            speaker_id="human",
                            speaker_name="You",
                            content="I want to plant tomatoes.",
                            occurred_at=1_700_000_002.0,
                            timestamp_confidence="exact",
                        )
                    ],
                )
            )
        return HistoryImportParseResult(sources=sources)


class _TimestampContractImporter:
    def __init__(self) -> None:
        self.inferred_occurred_at = 1_700_000_100.0

    async def parse(self, paths):  # type: ignore[no-untyped-def]
        return HistoryImportParseResult(
            sources=[
                HistoryImportSource(
                    source_id="timestamp-conversation",
                    source_name="Timestamp conversation",
                    session_key="timestamp-session",
                    records=[
                        HistoryImportRecord(
                            message_key="exact",
                            source_order=0,
                            speaker_id="human",
                            speaker_name="You",
                            content="Exact timestamp.",
                            occurred_at=1_700_000_000.0,
                            timestamp_confidence="exact",
                        ),
                        HistoryImportRecord(
                            message_key="source-order",
                            source_order=1,
                            speaker_id="assistant",
                            speaker_name="Assistant",
                            content="Source order only.",
                            timestamp_confidence="source_order",
                        ),
                        HistoryImportRecord(
                            message_key="inferred",
                            source_order=2,
                            speaker_id="human",
                            speaker_name="You",
                            content="Inferred timestamp.",
                            occurred_at=self.inferred_occurred_at,
                            timestamp_confidence="inferred",
                        ),
                        HistoryImportRecord(
                            message_key="unknown",
                            source_order=3,
                            speaker_id="assistant",
                            speaker_name="Assistant",
                            content="Unknown timestamp.",
                            timestamp_confidence="unknown",
                        ),
                    ],
                )
            ]
        )


class _OutOfOrderTimestampImporter:
    async def parse(self, paths):  # type: ignore[no-untyped-def]
        return HistoryImportParseResult(
            sources=[
                HistoryImportSource(
                    source_id="out-of-order-conversation",
                    source_name="Out-of-order conversation",
                    session_key="out-of-order-session",
                    records=[
                        HistoryImportRecord(
                            message_key="m0",
                            source_order=0,
                            speaker_id="human",
                            speaker_name="You",
                            content="First in the exported conversation.",
                            occurred_at=1_700_000_200.0,
                            timestamp_confidence="exact",
                        ),
                        HistoryImportRecord(
                            message_key="m1",
                            source_order=1,
                            speaker_id="assistant",
                            speaker_name="Assistant",
                            content="Second despite an older provider timestamp.",
                            occurred_at=1_700_000_050.0,
                            timestamp_confidence="exact",
                        ),
                        HistoryImportRecord(
                            message_key="m2",
                            source_order=2,
                            speaker_id="human",
                            speaker_name="You",
                            content="Third despite another timestamp regression.",
                            occurred_at=1_700_000_100.0,
                            timestamp_confidence="exact",
                        ),
                    ],
                )
            ]
        )


class _RecentSessionsImporter:
    async def parse(self, paths):  # type: ignore[no-untyped-def]
        def record(
            *,
            message_key: str,
            source_order: int,
            content: str,
            occurred_at: float,
        ) -> HistoryImportRecord:
            return HistoryImportRecord(
                message_key=message_key,
                source_order=source_order,
                speaker_id="human",
                speaker_name="You",
                content=content,
                occurred_at=occurred_at,
                timestamp_confidence="exact",
            )

        return HistoryImportParseResult(
            sources=[
                HistoryImportSource(
                    source_id="older-session",
                    source_name="Older session",
                    session_key="older-session",
                    records=[
                        record(
                            message_key="old-0",
                            source_order=0,
                            content="Older session first.",
                            occurred_at=120.0,
                        ),
                        record(
                            message_key="old-1",
                            source_order=1,
                            content="Older session second.",
                            occurred_at=100.0,
                        ),
                    ],
                ),
                HistoryImportSource(
                    source_id="recent-session",
                    source_name="Recent session",
                    session_key="recent-session",
                    records=[
                        record(
                            message_key="recent-0",
                            source_order=0,
                            content="Recent session first.",
                            occurred_at=300.0,
                        ),
                        record(
                            message_key="recent-1",
                            source_order=1,
                            content="Recent session second.",
                            occurred_at=200.0,
                        ),
                    ],
                ),
            ]
        )


class _BranchingArchiveImporter:
    async def parse(self, paths):  # type: ignore[no-untyped-def]
        branch = paths[0].read_text(encoding="utf-8").strip()
        records = [
            HistoryImportRecord(
                message_key="m1",
                source_order=0,
                speaker_id="human",
                speaker_name="You",
                role_hint="user",
                content="First message.",
            ),
            HistoryImportRecord(
                message_key="m2",
                source_order=1,
                speaker_id="assistant",
                speaker_name="Assistant",
                role_hint="assistant",
                content="Second message.",
                parent_message_key="m1",
            ),
        ]
        if branch != "base":
            shared = branch.startswith("same-")
            records.append(
                HistoryImportRecord(
                    message_key="m3-shared" if shared else f"m3-{branch}",
                    source_order=2,
                    speaker_id="human",
                    speaker_name="You",
                    role_hint="user",
                    content="Shared append." if shared else f"Append {branch}.",
                    parent_message_key="m2",
                )
            )
        return HistoryImportParseResult(
            sources=[
                HistoryImportSource(
                    source_id="branching-conversation",
                    source_name="Branching conversation",
                    session_key="stable-session",
                    records=records,
                )
            ]
        )


@pytest.fixture
async def platform_service(tmp_path: Path):
    db_path = tmp_path / "memory.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE l2_projection_jobs(" "event_id TEXT PRIMARY KEY, source TEXT NOT NULL)"
        )
        for statement in CREATE_STATEMENTS:
            await db.execute(statement)
        await db.executescript(SELECTION_SCHEMA_SQL)
        await db.executescript(IMPORTER_SCHEMA_SQL)
        await db.executescript(SOURCE_ROLE_SCHEMA_SQL)
        await db.commit()
    registry = HistoryImporterRegistry()
    importer = _ArchiveImporter()
    registry.register(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        importer=importer,
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Chat archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    memory = _Memory()
    service = HistoryImportService(
        store=HistoryImportStore(db_path=str(db_path)),
        memory=memory,
        importer_registry=registry,
    )
    yield service, importer, memory, tmp_path
    await service.stop()


async def _preview_branch(
    service: HistoryImportService,
    tmp_path: Path,
    branch: str,
) -> tuple[HistoryImportJob, str]:
    export = tmp_path / f"{branch}.json"
    export.write_text(branch, encoding="utf-8")
    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="branching-archive",
        importer_id="export",
        paths=[str(export)],
    )
    participant_id = next(
        item.participant_id for item in preview.participants if item.display_name == "You"
    )
    return preview, participant_id


@pytest.fixture
async def stored_platform_service(platform_service):
    from magi.memory import MemoryStoreTuning, UnifiedMemoryStore

    stub_service, importer, _stub_memory, tmp_path = platform_service
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "real-memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "real-memory.db"),
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
    await memory.initialize(start_workers=False)
    service = HistoryImportService(
        store=stub_service._store, memory=memory, importer_registry=stub_service._importer_registry
    )
    try:
        yield service, importer, memory, tmp_path
    finally:
        await service.stop()
        await memory.shutdown()


async def _platform_ledger_snapshot(service):
    async with aiosqlite.connect(service._store.db_path) as db:
        return {
            table: await (await db.execute(f"SELECT * FROM {table} ORDER BY rowid")).fetchall()
            for table in (
                "history_import_jobs",
                "history_import_source_records",
                "history_import_job_records",
            )
        }


async def _confirm_branch(
    service: HistoryImportService,
    preview: HistoryImportJob,
    participant_id: str,
) -> HistoryImportJob:
    return await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=False,
        included_source_ids=["branching-conversation"],
        self_participant_ids=[participant_id],
    )


@pytest.mark.asyncio
async def test_platform_preview_selects_session_and_host_confirms_self_identity(
    platform_service,
) -> None:
    service, _importer, memory, tmp_path = platform_service
    export = tmp_path / "export.json"
    export.write_text("{}", encoding="utf-8")

    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )

    assert preview.source_ids == ["conversation-1"]
    assert preview.sources[0].detected_kind == "chat"
    participant_names = {item.display_name for item in preview.participants}
    assert participant_names == {"You"}
    assert all(item.participant_id.startswith("hip_") for item in preview.participants)
    human_participant_id = next(
        item.participant_id for item in preview.participants if item.display_name == "You"
    )
    ready = await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=False,
        included_source_ids=["conversation-1"],
        self_participant_ids=[human_participant_id],
    )

    assert ready.quick_ready is True
    assert len(memory.raw_events) == 2
    assert all(event.event_type == "history_import.chat" for event in memory.raw_events)
    assert all(
        event.metadata_json["history_import"]["source_kind"] == "chat"
        for event in memory.raw_events
    )
    await service._tasks[preview.job_id]
    assert [event.content for event in memory.projected_events] == [
        "Why do I keep returning to pottery?"
    ]
    assert memory.raw_events[1].metadata_json["history_import"]["parent_message_key"] == "m1"
    assert [event.author_type for event in memory.raw_events] == ["user", "assistant"]
    assert [event.cognition_eligible for event in memory.raw_events] == [True, False]
    assert memory.raw_events[1].metadata_json["history_import"]["source_role"] == "assistant"


@pytest.mark.asyncio
@pytest.mark.parametrize("identical", [False, True])
async def test_concurrent_confirmation_preserves_one_append_and_exact_memory_effects(
    stored_platform_service, identical
):
    service, _importer, memory, tmp_path = stored_platform_service
    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="branching-archive",
        importer_id="export",
        importer=_BranchingArchiveImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Branching archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    base, base_participant = await _preview_branch(service, tmp_path, "base")
    await _confirm_branch(service, base, base_participant)
    await service._tasks[base.job_id]
    first, first_participant = await _preview_branch(
        service, tmp_path, "same-first" if identical else "first"
    )
    second, second_participant = await _preview_branch(
        service, tmp_path, "same-second" if identical else "second"
    )
    results = await asyncio.gather(
        _confirm_branch(service, first, first_participant),
        _confirm_branch(service, second, second_participant),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, HistoryImportJob)]
    failures = [r for r in results if isinstance(r, HistoryImportValidationError)]
    assert len(successes) == (2 if identical else 1)
    assert [r.reason for r in failures] == (
        [] if identical else ["history_importer_non_append_update"]
    )
    await asyncio.gather(
        *(service._tasks[job.job_id] for job in successes if job.job_id in service._tasks)
    )
    winning = successes[0]
    branch = "first" if winning.job_id == first.job_id else "second"
    appended_key = "m3-shared" if identical else f"m3-{branch}"
    appended_content = "Shared append." if identical else f"Append {branch}."
    records = await service._store.list_source_records(
        job_id=winning.job_id, source_id="branching-conversation", limit=10
    )
    assert [(r.message_key, r.content) for r in records] == [
        ("m1", "First message."),
        ("m2", "Second message."),
        (appended_key, appended_content),
    ]
    async with aiosqlite.connect(memory.l1.db_path) as db:
        raw_rows = await (
            await db.execute("SELECT event_id,content FROM fact_events ORDER BY event_id")
        ).fetchall()
    assert raw_rows == sorted((r.event_id, r.content) for r in records)
    async with aiosqlite.connect(memory.l2.db_path) as db:
        jobs = await (
            await db.execute("SELECT event_id FROM l2_projection_jobs ORDER BY event_id")
        ).fetchall()
    assert jobs == sorted([(records[0].event_id,), (records[2].event_id,)])
    other = second if winning.job_id == first.job_id else first
    other_records = await service._store.list_source_records(
        job_id=other.job_id, source_id="branching-conversation", limit=10
    )
    if identical:
        assert [(r.source_record_key, r.event_id) for r in other_records] == [
            (r.source_record_key, r.event_id) for r in records
        ]
        async with aiosqlite.connect(service._store.db_path) as db:
            assert (
                await (
                    await db.execute("SELECT COUNT(*) FROM history_import_source_records")
                ).fetchone()
            )[0] == 3
            assert (
                await (
                    await db.execute("SELECT COUNT(*) FROM history_import_job_records")
                ).fetchone()
            )[0] == 8
    else:
        loser = await service.get_job(other.job_id)
        assert (loser.status, loser.quick_ready, loser.self_participant_ids) == (
            "preview_ready",
            False,
            [],
        )
        assert [(r.raw_state, r.projection_state) for r in other_records] == [
            ("pending", "pending")
        ] * 3


@pytest.mark.asyncio
async def test_source_scoped_participants_do_not_merge_reused_raw_speaker_ids(
    platform_service,
) -> None:
    service, importer, memory, tmp_path = platform_service
    importer.include_second_source = True
    export = tmp_path / "source-scoped.json"
    export.write_text("{}", encoding="utf-8")

    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )

    user_participants = [item for item in preview.participants if item.display_name == "You"]
    assert len(user_participants) == 2
    assert len({item.participant_id for item in user_participants}) == 2

    selected = user_participants[0].participant_id
    records = [
        record
        for source in preview.included_source_ids
        for record in await service._store.list_source_records(
            job_id=preview.job_id, source_id=source, limit=10
        )
    ]
    selected_records = [record for record in records if record.speaker_id == selected]
    assert len(selected_records) == 1
    expected = selected_records[0]
    expected_content = {
        "conversation-1": "Why do I keep returning to pottery?",
        "conversation-2": "I want to plant tomatoes.",
    }[expected.source_id]
    await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=False,
        included_source_ids=preview.included_source_ids,
        self_participant_ids=[user_participants[0].participant_id],
    )
    await service._tasks[preview.job_id]

    assert [(event.event_id, event.content) for event in memory.projected_events] == [
        (expected.event_id, expected_content)
    ]


@pytest.mark.asyncio
async def test_export_scoped_participants_merge_reused_raw_speaker_ids(
    platform_service,
) -> None:
    service, importer, memory, tmp_path = platform_service
    importer.include_second_source = True
    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="export-scoped-archive",
        importer_id="export",
        importer=importer,
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Export-scoped archive",
            accepted_extensions=["json"],
            format_version="1",
            participant_identity_scope="export",
        ),
    )
    export = tmp_path / "export-scoped.json"
    export.write_text("{}", encoding="utf-8")

    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="export-scoped-archive",
        importer_id="export",
        paths=[str(export)],
    )

    user_participants = [item for item in preview.participants if item.display_name == "You"]
    assert len(user_participants) == 1
    assert user_participants[0].message_count == 2

    await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=False,
        included_source_ids=preview.included_source_ids,
        self_participant_ids=[user_participants[0].participant_id],
    )
    await service._tasks[preview.job_id]

    assert {event.content for event in memory.projected_events} == {
        "Why do I keep returning to pottery?",
        "I want to plant tomatoes.",
    }


@pytest.mark.asyncio
async def test_platform_importer_cannot_use_reserved_document_participant_id(
    platform_service,
) -> None:
    service, _importer, _memory, tmp_path = platform_service

    class _ReservedParticipantImporter:
        async def parse(self, paths):  # type: ignore[no-untyped-def]
            return HistoryImportParseResult(
                sources=[
                    HistoryImportSource(
                        source_id="reserved-session",
                        source_name="Reserved session",
                        session_key="reserved-session",
                        records=[
                            HistoryImportRecord(
                                message_key="m1",
                                source_order=0,
                                speaker_id="__document_author__",
                                speaker_name="You",
                                content="A valid message.",
                            )
                        ],
                    )
                ]
            )

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="reserved-participant",
        importer_id="export",
        importer=_ReservedParticipantImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Reserved participant",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "reserved.json"
    export.write_text("{}", encoding="utf-8")

    with pytest.raises(HistoryImportValidationError) as exc_info:
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="reserved-participant",
            importer_id="export",
            paths=[str(export)],
        )

    assert exc_info.value.reason == "history_importer_reserved_participant_id"


@pytest.mark.asyncio
async def test_incremental_export_reuses_old_message_identity_and_anchors_missing_time(
    platform_service,
) -> None:
    service, importer, _memory, tmp_path = platform_service
    export = tmp_path / "export.json"
    export.write_text('{"version":1}', encoding="utf-8")
    os.utime(export, (1_600_000_000, 1_600_000_000))
    first = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )
    first_records = await service._store.list_source_records(
        job_id=first.job_id,
        source_id="conversation-1",
        limit=10,
    )

    importer.include_new_message = True
    export.write_text('{"version":2}', encoding="utf-8")
    os.utime(export, (1_600_000_100, 1_600_000_100))
    second = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )
    second_records = await service._store.list_source_records(
        job_id=second.job_id,
        source_id="conversation-1",
        limit=10,
    )

    assert [item.event_id for item in second_records[:2]] == [
        item.event_id for item in first_records
    ]
    assert second_records[2].timestamp_confidence == "unknown"
    assert second_records[2].timestamp_anchor_source == "source_order"
    assert 1_700_000_001.0 < second_records[2].event_at < 1_700_000_002.0


@pytest.mark.asyncio
async def test_platform_timestamp_contract_anchors_only_untimed_records(
    platform_service,
) -> None:
    service, _importer, _memory, tmp_path = platform_service
    importer = _TimestampContractImporter()
    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="timestamp-archive",
        importer_id="export",
        importer=importer,
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Timestamp archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "timestamps.json"
    export.write_text("{}", encoding="utf-8")

    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="timestamp-archive",
        importer_id="export",
        paths=[str(export)],
    )
    records = await service._store.list_source_records(
        job_id=preview.job_id,
        source_id="timestamp-conversation",
        limit=10,
    )

    assert [record.timestamp_confidence for record in records] == [
        "exact",
        "source_order",
        "inferred",
        "unknown",
    ]
    assert records[0].event_at == 1_700_000_000.0
    assert records[0].timestamp_anchor_source == "source_timestamp"
    assert records[2].event_at == 1_700_000_100.0
    assert records[2].timestamp_anchor_source == "source_timestamp"
    assert 1_700_000_000.0 < records[1].event_at < 1_700_000_100.0
    assert records[1].timestamp_anchor_source == "source_order"
    assert records[3].event_at > 1_700_000_100.0
    assert records[3].timestamp_anchor_source == "source_order"


@pytest.mark.asyncio
async def test_platform_import_preserves_source_order_when_timestamps_regress(
    platform_service,
) -> None:
    service, _importer, memory, tmp_path = platform_service
    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="out-of-order-archive",
        importer_id="export",
        importer=_OutOfOrderTimestampImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Out-of-order archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "out-of-order.json"
    export.write_text("{}", encoding="utf-8")

    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="out-of-order-archive",
        importer_id="export",
        paths=[str(export)],
    )
    pending = await service._store.list_pending_raw_records(
        job_id=preview.job_id,
        limit=10,
    )
    participant_id = next(
        item.participant_id for item in preview.participants if item.display_name == "You"
    )
    await service.confirm(
        job_id=preview.job_id,
        confirm_personal_writing=False,
        included_source_ids=preview.included_source_ids,
        self_participant_ids=[participant_id],
    )
    await service._tasks[preview.job_id]

    assert [record.session_seq for record in pending] == [0, 1, 2]
    assert [event.session_seq for event in memory.raw_events] == [0, 1, 2]
    assert [event.session_seq for event in memory.projected_events] == [0, 2]


@pytest.mark.asyncio
async def test_platform_quick_selection_prefers_recent_sessions_then_source_order(
    platform_service,
) -> None:
    service, _importer, _memory, tmp_path = platform_service
    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="recent-sessions-archive",
        importer_id="export",
        importer=_RecentSessionsImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Recent sessions archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "recent-sessions.json"
    export.write_text("{}", encoding="utf-8")

    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="recent-sessions-archive",
        importer_id="export",
        paths=[str(export)],
    )
    quick = await service._store.select_quick_records(job_id=preview.job_id)
    pending = await service._store.list_pending_raw_records(job_id=preview.job_id, limit=10)

    assert [record.content for record in quick] == [
        "Recent session first.",
        "Recent session second.",
        "Older session first.",
        "Older session second.",
    ]
    assert [record.content for record in pending] == [
        "Older session first.",
        "Older session second.",
        "Recent session first.",
        "Recent session second.",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["content", "exact_timestamp", "inferred_timestamp"])
async def test_importer_message_identity_rejects_mutation_without_partial_ledger_changes(
    platform_service, changed_field
):
    service, default_importer, memory, tmp_path = platform_service
    importer = (
        _TimestampContractImporter() if changed_field == "inferred_timestamp" else default_importer
    )
    plugin_id = "timestamp-archive" if changed_field == "inferred_timestamp" else "chat-archive"
    if changed_field == "inferred_timestamp":
        service._importer_registry.register(
            connection_id="archive-connection",
            plugin_id=plugin_id,
            importer_id="export",
            importer=importer,
            spec=HistoryImporterSpec(
                importer_id="export",
                display_name="Timestamp archive",
                accepted_extensions=["json"],
                format_version="1",
            ),
        )
    export = tmp_path / "export.json"
    export.write_text('{"version":1}')
    await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id=plugin_id,
        importer_id="export",
        paths=[str(export)],
    )
    before = await _platform_ledger_snapshot(service)
    assert all(before.values())
    if changed_field == "content":
        importer.change_first_message = True
    elif changed_field == "exact_timestamp":
        importer.change_first_timestamp = True
    else:
        importer.inferred_occurred_at += 1
    export.write_text('{"version":2}')
    with pytest.raises(HistoryImportValidationError, match="history_importer_invalid_output"):
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id=plugin_id,
            importer_id="export",
            paths=[str(export)],
        )
    assert await _platform_ledger_snapshot(service) == before
    assert memory.raw_events == memory.projected_events == []


@pytest.mark.asyncio
async def test_incremental_export_rejects_non_append_message_order_changes(
    platform_service,
) -> None:
    service, importer, _memory, tmp_path = platform_service
    export = tmp_path / "export.json"
    export.write_text('{"version":1}', encoding="utf-8")
    first = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )
    first_records = await service._store.list_source_records(
        job_id=first.job_id,
        source_id="conversation-1",
        limit=10,
    )
    await service.confirm(
        job_id=first.job_id,
        confirm_personal_writing=False,
        included_source_ids=first.included_source_ids,
        self_participant_ids=[
            next(item.participant_id for item in first.participants if item.display_name == "You")
        ],
    )
    await service._tasks[first.job_id]

    before = await _platform_ledger_snapshot(service)
    original_contents = [event.content for event in _memory.raw_events]
    importer.prepend_old_message = True
    export.write_text('{"version":2}', encoding="utf-8")
    with pytest.raises(HistoryImportValidationError) as exc_info:
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="chat-archive",
            importer_id="export",
            paths=[str(export)],
        )

    assert exc_info.value.reason == "history_importer_non_append_update"
    reread = await service._store.list_source_records(
        job_id=first.job_id, source_id="conversation-1", limit=10
    )
    assert [(r.message_key, r.content, r.event_at, r.event_id) for r in reread] == [
        (r.message_key, r.content, r.event_at, r.event_id) for r in first_records
    ]
    assert [r.message_key for r in reread] == ["m1", "m2"]
    assert await _platform_ledger_snapshot(service) == before
    assert [event.content for event in _memory.raw_events] == original_contents


@pytest.mark.asyncio
async def test_display_labels_and_host_timezone_do_not_change_message_identity(
    platform_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, importer, _memory, tmp_path = platform_service
    export = tmp_path / "export.json"
    export.write_text('{"version":1}', encoding="utf-8")
    monkeypatch.setattr(
        "magi.memory.history_imports.service.local_calendar_timezone_id",
        lambda: "Asia/Shanghai",
    )
    first = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )
    first_records = await service._store.list_source_records(
        job_id=first.job_id,
        source_id="conversation-1",
        limit=10,
    )

    importer.source_name = "Renamed conversation"
    importer.user_display_name = "Me"
    export.write_text('{"version":2}', encoding="utf-8")
    monkeypatch.setattr(
        "magi.memory.history_imports.service.local_calendar_timezone_id",
        lambda: "America/Los_Angeles",
    )
    second = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )
    second_records = await service._store.list_source_records(
        job_id=second.job_id,
        source_id="conversation-1",
        limit=10,
    )

    assert [item.event_id for item in second_records] == [item.event_id for item in first_records]


@pytest.mark.asyncio
async def test_same_session_and_message_keys_in_different_sources_do_not_collide(
    platform_service,
) -> None:
    service, importer, _memory, tmp_path = platform_service
    importer.include_second_source = True
    export = tmp_path / "export.json"
    export.write_text("{}", encoding="utf-8")

    preview = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )
    first = await service._store.list_source_records(
        job_id=preview.job_id,
        source_id="conversation-1",
        limit=10,
    )
    second = await service._store.list_source_records(
        job_id=preview.job_id,
        source_id="conversation-2",
        limit=10,
    )

    assert first[0].message_key == second[0].message_key == "m1"
    assert first[0].event_id != second[0].event_id
    assert first[0].session_id != second[0].session_id


@pytest.mark.asyncio
async def test_importer_preview_times_out_with_stable_reason(
    platform_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _importer, _memory, tmp_path = platform_service
    worker_started = threading.Event()
    worker_finished = threading.Event()
    heartbeat_seen = asyncio.Event()

    class _SlowImporter:
        async def parse(self, paths):  # type: ignore[no-untyped-def]
            worker_started.set()
            time.sleep(0.1)
            worker_finished.set()

    async def heartbeat() -> None:
        while not worker_started.is_set():
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)
        heartbeat_seen.set()

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="slow-archive",
        importer_id="export",
        importer=_SlowImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Slow archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    monkeypatch.setattr(
        "magi.memory.history_imports.service.IMPORTER_PARSE_TIMEOUT_SECONDS",
        0.03,
    )
    export = tmp_path / "slow.json"
    export.write_text("{}", encoding="utf-8")
    heartbeat_task = asyncio.create_task(heartbeat())

    with pytest.raises(HistoryImportValidationError) as exc_info:
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="slow-archive",
            importer_id="export",
            paths=[str(export)],
        )

    assert exc_info.value.reason == "history_importer_timeout"
    await asyncio.wait_for(heartbeat_task, timeout=1)
    assert heartbeat_seen.is_set()
    assert not worker_finished.is_set()
    assert await asyncio.to_thread(worker_finished.wait, 1)


@pytest.mark.asyncio
async def test_importer_preview_limits_timed_out_workers_to_two(
    platform_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _importer, _memory, tmp_path = platform_service
    state_lock = threading.Lock()
    two_workers_started = threading.Event()
    release_workers = threading.Event()
    all_workers_finished = threading.Event()
    started_count = 0
    active_count = 0
    max_active_count = 0

    class _BlockingImporter:
        async def parse(self, paths):  # type: ignore[no-untyped-def]
            nonlocal active_count, max_active_count, started_count
            with state_lock:
                started_count += 1
                active_count += 1
                max_active_count = max(max_active_count, active_count)
                if started_count == 2:
                    two_workers_started.set()
            try:
                release_workers.wait(timeout=1)
                return HistoryImportParseResult(sources=[])
            finally:
                with state_lock:
                    active_count -= 1
                    if active_count == 0:
                        all_workers_finished.set()

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="blocking-archive",
        importer_id="export",
        importer=_BlockingImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Blocking archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    monkeypatch.setattr(
        "magi.memory.history_imports.service.IMPORTER_PARSE_TIMEOUT_SECONDS",
        0.1,
    )
    export = tmp_path / "blocking.json"
    export.write_text("{}", encoding="utf-8")
    previews = [
        asyncio.create_task(
            service.preview_importer_paths(
                connection_id="archive-connection",
                plugin_id="blocking-archive",
                importer_id="export",
                paths=[str(export)],
            )
        )
        for _ in range(3)
    ]

    try:
        assert await asyncio.to_thread(two_workers_started.wait, 1)
        results = await asyncio.gather(*previews, return_exceptions=True)
    finally:
        release_workers.set()
        assert await asyncio.to_thread(all_workers_finished.wait, 1)

        async def wait_for_worker_cleanup() -> None:
            while service._importer_parse_tasks:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_worker_cleanup(), timeout=1)

    assert all(isinstance(result, HistoryImportValidationError) for result in results)
    assert [result.reason for result in results] == [
        "history_importer_timeout",
        "history_importer_timeout",
        "history_importer_timeout",
    ]
    assert started_count == 2
    assert max_active_count == 2
    assert not service._importer_parse_tasks


@pytest.mark.asyncio
async def test_importer_output_budget_is_checked_before_deep_revalidation(
    platform_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _importer, _memory, tmp_path = platform_service

    class _OverBudgetImporter:
        def parse(self, paths):  # type: ignore[no-untyped-def]
            source = HistoryImportSource.model_construct(
                source_id="oversized-session",
                source_name="Oversized session",
                session_key="oversized-session",
                detected_kind="chat",
                records=[object(), object()],
                warnings=[],
            )
            return HistoryImportParseResult.model_construct(sources=[source], warnings=[])

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="oversized-archive",
        importer_id="export",
        importer=_OverBudgetImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Oversized archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    monkeypatch.setattr(history_import_service_module, "MAX_IMPORTER_TOTAL_RECORDS", 1)
    export = tmp_path / "oversized.json"
    export.write_text("{}", encoding="utf-8")

    with pytest.raises(HistoryImportValidationError) as exc_info:
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="oversized-archive",
            importer_id="export",
            paths=[str(export)],
        )

    assert exc_info.value.reason == "history_importer_output_too_large"


@pytest.mark.asyncio
async def test_importer_output_revalidation_runs_in_parser_worker(
    platform_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _importer, _memory, tmp_path = platform_service
    caller_thread_id = threading.get_ident()
    validation_thread_ids: list[int] = []
    original = history_import_service_module._revalidate_importer_output

    def observed_revalidation(value):  # type: ignore[no-untyped-def]
        validation_thread_ids.append(threading.get_ident())
        return original(value)

    monkeypatch.setattr(
        history_import_service_module,
        "_revalidate_importer_output",
        observed_revalidation,
    )
    export = tmp_path / "worker-validation.json"
    export.write_text("{}", encoding="utf-8")

    await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(export)],
    )

    assert validation_thread_ids
    assert all(thread_id != caller_thread_id for thread_id in validation_thread_ids)


@pytest.mark.asyncio
async def test_importer_preview_rejects_a_file_changed_during_parse(
    platform_service,
) -> None:
    service, _importer, _memory, tmp_path = platform_service

    class _MutatingImporter:
        async def parse(self, paths):  # type: ignore[no-untyped-def]
            paths[0].write_text('{"changed":true}', encoding="utf-8")
            return HistoryImportParseResult(
                sources=[
                    HistoryImportSource(
                        source_id="mutating-session",
                        source_name="Mutating session",
                        session_key="mutating-session",
                        records=[
                            HistoryImportRecord(
                                message_key="m1",
                                source_order=0,
                                speaker_id="human",
                                speaker_name="You",
                                content="A valid message.",
                            )
                        ],
                    )
                ]
            )

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="mutating-archive",
        importer_id="export",
        importer=_MutatingImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Mutating archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "mutating.json"
    export.write_text("{}", encoding="utf-8")

    with pytest.raises(HistoryImportValidationError) as exc_info:
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="mutating-archive",
            importer_id="export",
            paths=[str(export)],
        )

    assert exc_info.value.reason == "history_import_selection_changed"


@pytest.mark.asyncio
async def test_importer_parse_does_not_block_clear_and_rejects_stale_result(
    platform_service,
) -> None:
    service, _importer, memory, tmp_path = platform_service
    parse_started = threading.Event()
    release_parse = threading.Event()

    class _PausedImporter:
        async def parse(self, paths):  # type: ignore[no-untyped-def]
            parse_started.set()
            release_parse.wait()
            return HistoryImportParseResult(
                sources=[
                    HistoryImportSource(
                        source_id="paused-session",
                        source_name="Paused session",
                        session_key="paused-session",
                        records=[
                            HistoryImportRecord(
                                message_key="m1",
                                source_order=0,
                                speaker_id="human",
                                speaker_name="You",
                                content="A valid message.",
                            )
                        ],
                    )
                ]
            )

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="paused-archive",
        importer_id="export",
        importer=_PausedImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Paused archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "paused.json"
    export.write_text("{}", encoding="utf-8")
    preview_task = asyncio.create_task(
        service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="paused-archive",
            importer_id="export",
            paths=[str(export)],
        )
    )
    try:
        assert await asyncio.to_thread(parse_started.wait, 1)
        before = await _platform_ledger_snapshot(service)
        assert all(not rows for rows in before.values())

        async def clear_while_parser_is_blocked():
            async with service.user_content_clear_boundary():
                memory.epoch += 1

        await asyncio.wait_for(clear_while_parser_is_blocked(), timeout=1)
        assert not preview_task.done()
        release_parse.set()
        with pytest.raises(HistoryImportValidationError, match="memory_cleared_during_import"):
            await asyncio.wait_for(preview_task, timeout=1)
        assert await _platform_ledger_snapshot(service) == before
        assert memory.raw_events == memory.projected_events == []
    finally:
        release_parse.set()
        if not preview_task.done():
            preview_task.cancel()
        await asyncio.gather(preview_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stop_generation_fences_an_inflight_importer_result_after_restart(
    platform_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _importer, _memory, tmp_path = platform_service
    parse_started = threading.Event()
    release_parse = threading.Event()

    class _PausedImporter:
        def parse(self, paths):  # type: ignore[no-untyped-def]
            parse_started.set()
            release_parse.wait(timeout=1)
            return HistoryImportParseResult(
                sources=[
                    HistoryImportSource(
                        source_id="stopped-session",
                        source_name="Stopped session",
                        session_key="stopped-session",
                        records=[
                            HistoryImportRecord(
                                message_key="m1",
                                source_order=0,
                                speaker_id="human",
                                speaker_name="You",
                                content="This result must not survive service shutdown.",
                            )
                        ],
                    )
                ]
            )

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="stopped-archive",
        importer_id="export",
        importer=_PausedImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Stopped archive",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    monkeypatch.setattr(
        history_import_service_module,
        "IMPORTER_PARSE_SHUTDOWN_GRACE_SECONDS",
        0.01,
    )
    export = tmp_path / "stopped.json"
    export.write_text("{}", encoding="utf-8")
    preview_task = asyncio.create_task(
        service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="stopped-archive",
            importer_id="export",
            paths=[str(export)],
        )
    )

    try:
        assert await asyncio.to_thread(parse_started.wait, 1)
        await service.stop()
        assert service._importer_parse_tasks
        await service.start()
    finally:
        release_parse.set()

    with pytest.raises(HistoryImportValidationError) as exc_info:
        await asyncio.wait_for(preview_task, timeout=1)
    assert exc_info.value.reason == "history_importer_not_available"
    assert await service._store.list_active_jobs(limit=10) == []


@pytest.mark.asyncio
async def test_importer_preview_fingerprint_is_independent_of_picker_order(
    platform_service,
) -> None:
    service, _importer, _memory, tmp_path = platform_service
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text('{"part":1}', encoding="utf-8")
    second_path.write_text('{"part":2}', encoding="utf-8")

    first = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(first_path), str(second_path)],
    )
    second = await service.preview_importer_paths(
        connection_id="archive-connection",
        plugin_id="chat-archive",
        importer_id="export",
        paths=[str(second_path), str(first_path)],
    )

    assert second.job_id == first.job_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parse_result", "reason"),
    [
        (RuntimeError("private parser detail"), "history_importer_parse_failed"),
        ({"sources": []}, "history_importer_invalid_output"),
    ],
)
async def test_importer_failures_are_mapped_to_stable_host_reasons(
    platform_service,
    parse_result,
    reason: str,
) -> None:
    service, _importer, _memory, tmp_path = platform_service

    class _BoundaryImporter:
        async def parse(self, paths):  # type: ignore[no-untyped-def]
            if isinstance(parse_result, Exception):
                raise parse_result
            return parse_result

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="boundary",
        importer_id="export",
        importer=_BoundaryImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Boundary",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "boundary.json"
    export.write_text("{}", encoding="utf-8")

    with pytest.raises(HistoryImportValidationError) as exc_info:
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="boundary",
            importer_id="export",
            paths=[str(export)],
        )

    assert exc_info.value.reason == reason
    assert "private parser detail" not in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("corruption", "expected_reason"),
    [
        ("constructed_non_finite_timestamp", "history_importer_invalid_output"),
        ("duplicate_message_key", "history_importer_invalid_output"),
        ("duplicate_source_order", "history_importer_invalid_output"),
        ("oversized_content", "history_importer_output_too_large"),
        ("unknown_parent", "history_importer_invalid_output"),
    ],
)
async def test_importer_preview_deeply_revalidates_pydantic_results(
    platform_service,
    corruption: str,
    expected_reason: str,
) -> None:
    service, _importer, _memory, tmp_path = platform_service

    class _CorruptedModelImporter:
        async def parse(self, paths):  # type: ignore[no-untyped-def]
            record = HistoryImportRecord(
                message_key="m1",
                source_order=0,
                speaker_id="human",
                speaker_name="You",
                content="A valid message.",
            )
            source = HistoryImportSource(
                source_id="corrupted-session",
                source_name="Corrupted session",
                session_key="corrupted-session",
                records=[record],
            )
            result = HistoryImportParseResult(sources=[source])
            if corruption == "constructed_non_finite_timestamp":
                invalid_record = HistoryImportRecord.model_construct(
                    message_key="m1",
                    source_order=0,
                    speaker_id="human",
                    speaker_name="You",
                    content="A valid message.",
                    occurred_at=float("nan"),
                    timestamp_confidence="exact",
                )
                invalid_source = HistoryImportSource.model_construct(
                    source_id="corrupted-session",
                    source_name="Corrupted session",
                    session_key="corrupted-session",
                    records=[invalid_record],
                    warnings=[],
                )
                return HistoryImportParseResult.model_construct(
                    sources=[invalid_source],
                    warnings=[],
                )
            if corruption == "duplicate_message_key":
                source.records.append(record.model_copy(update={"source_order": 1}))
            elif corruption == "duplicate_source_order":
                source.records.append(record.model_copy(update={"message_key": "m2"}))
            elif corruption == "oversized_content":
                record.content = "x" * (MAX_HISTORY_IMPORT_CONTENT_LENGTH + 1)
            else:
                record.parent_message_key = "missing"
            return result

    service._importer_registry.register(
        connection_id="archive-connection",
        plugin_id="corrupted-model",
        importer_id="export",
        importer=_CorruptedModelImporter(),
        spec=HistoryImporterSpec(
            importer_id="export",
            display_name="Corrupted model",
            accepted_extensions=["json"],
            format_version="1",
        ),
    )
    export = tmp_path / "corrupted.json"
    export.write_text("{}", encoding="utf-8")

    with pytest.raises(HistoryImportValidationError) as exc_info:
        await service.preview_importer_paths(
            connection_id="archive-connection",
            plugin_id="corrupted-model",
            importer_id="export",
            paths=[str(export)],
        )

    assert exc_info.value.reason == expected_reason


@pytest.mark.asyncio
async def test_same_package_importers_keep_connection_data_separate(platform_service) -> None:
    service, first_importer, _memory, tmp_path = platform_service
    archive = tmp_path / "same-export.json"
    archive.write_text("{}")
    second_importer = _ArchiveImporter()
    second_importer.change_first_message = True
    first_registration = service._importer_registry.get(
        "chat-archive", "export", connection_id="archive-connection"
    )
    service._importer_registry.register(
        plugin_id="chat-archive", importer_id="export", connection_id="second-account",
        importer=second_importer, spec=first_registration.spec,
    )
    first = await service.preview_importer_paths(
        plugin_id="chat-archive", importer_id="export", connection_id="archive-connection",
        paths=[str(archive)],
    )
    second = await service.preview_importer_paths(
        plugin_id="chat-archive", importer_id="export", connection_id="second-account",
        paths=[str(archive)],
    )
    assert first.connection_id == "archive-connection"
    assert second.connection_id == "second-account"
    assert first.job_id != second.job_id
    assert first.source_fingerprint != second.source_fingerprint
    assert [record.content for record in first.preview_records] != [record.content for record in second.preview_records]
    assert first.preview_records[0].session_id != second.preview_records[0].session_id
    assert first.preview_records[0].source_record_key != second.preview_records[0].source_record_key
    assert first.preview_records[0].speaker_id != second.preview_records[0].speaker_id
    assert (await service.get_job(second.job_id)).connection_id == "second-account"
    with pytest.raises(HistoryImportValidationError, match="history_importer_not_available"):
        await service.preview_importer_paths(
            plugin_id="chat-archive", importer_id="export", connection_id="unknown-account",
            paths=[str(archive)],
        )


async def _preview_role_archive(service, tmp_path, version="initial"):
    export = tmp_path / "roles.json"
    export.write_text(version, encoding="utf-8")
    return await service.preview_importer_paths(
        connection_id="archive-connection", plugin_id="chat-archive", importer_id="export",
        paths=[str(export)],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["assistant", "other"])
async def test_source_role_survives_reopen_and_cannot_be_confirmed_as_self(
    platform_service, monkeypatch, role
):
    service, importer, memory, tmp_path = platform_service
    parse = importer.parse

    async def parse_roles(paths):
        result = await parse(paths)
        result.sources[0].records[1] = result.sources[0].records[1].model_copy(
            update={"role_hint": role}
        )
        return result

    monkeypatch.setattr(importer, "parse", parse_roles)
    preview = await _preview_role_archive(service, tmp_path)
    reopened = HistoryImportStore(db_path=service._store.db_path)
    persisted = await reopened.get_job(preview.job_id)
    blocked = next(record for record in persisted.preview_records if record.source_role == role)
    assert {item.display_name for item in persisted.participants} == {"You"}
    before = await _platform_ledger_snapshot(service)
    with pytest.raises(HistoryImportValidationError, match="self_participant_required"):
        await service.confirm(
            job_id=preview.job_id, self_participant_ids=[blocked.speaker_id],
            included_source_ids=preview.source_ids, confirm_personal_writing=False,
        )
    with pytest.raises(ValueError, match="speaker_role_conflict"):
        await reopened.set_scope(
            job_id=preview.job_id, self_participant_ids=[blocked.speaker_id],
            included_source_ids=preview.source_ids,
        )
    assert await _platform_ledger_snapshot(service) == before
    assert memory.raw_events == memory.projected_events == []


@pytest.mark.asyncio
async def test_mixed_source_roles_cannot_launder_an_assistant_through_a_user_id(
    platform_service, monkeypatch
):
    service, importer, _memory, tmp_path = platform_service
    parse = importer.parse

    async def parse_roles(paths):
        result = await parse(paths)
        result.sources[0].records[1] = result.sources[0].records[1].model_copy(
            update={"speaker_id": "human"}
        )
        return result

    monkeypatch.setattr(importer, "parse", parse_roles)
    preview = await _preview_role_archive(service, tmp_path)
    assert preview.participants == []
    with pytest.raises(ValueError, match="speaker_role_conflict"):
        await service._store.set_scope(
            job_id=preview.job_id, self_participant_ids=[preview.preview_records[0].speaker_id],
            included_source_ids=preview.source_ids,
        )


@pytest.mark.asyncio
async def test_reimport_cannot_change_source_role_for_existing_message(
    platform_service, monkeypatch
):
    service, importer, _memory, tmp_path = platform_service
    await _preview_role_archive(service, tmp_path)
    before = await _platform_ledger_snapshot(service)
    parse = importer.parse
    importer.include_new_message = True

    async def parse_roles(paths):
        result = await parse(paths)
        result.sources[0].records[1] = result.sources[0].records[1].model_copy(
            update={"role_hint": "user"}
        )
        return result

    monkeypatch.setattr(importer, "parse", parse_roles)
    with pytest.raises(HistoryImportValidationError, match="history_importer_invalid_output") as exc:
        await _preview_role_archive(service, tmp_path, version="updated")
    assert str(exc.value.__cause__) == "history_import_source_identity_conflict"
    assert await _platform_ledger_snapshot(service) == before


@pytest.mark.asyncio
async def test_deleting_confirmed_job_does_not_turn_assistant_into_selectable_user(stored_platform_service):
    service, _importer, _memory, tmp_path = stored_platform_service
    preview = await _preview_role_archive(service, tmp_path)
    await service.confirm(
        job_id=preview.job_id, self_participant_ids=[preview.participants[0].participant_id],
        included_source_ids=preview.source_ids, confirm_personal_writing=False,
    )
    await service._tasks[preview.job_id]
    await service.delete(preview.job_id)
    reimport = await _preview_role_archive(service, tmp_path)
    assert {item.display_name for item in reimport.participants} == {"You"}
    assert [record.source_role for record in reimport.preview_records] == ["user", "assistant"]
