from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from magi.chat.asset_gc import ChatAssetGC
from magi.core.chat_assets.mutations import (
    chat_asset_mutation,
    run_chat_asset_mutation,
)
from magi.chat.asset_validation import ChatAssetOwnershipError
from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
from magi.chat.contracts import ChatMessageRecord
from magi.chat.store import ChatStore


async def _wait_for_thread_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 2)


@pytest.mark.asyncio
async def test_cancelled_lock_waiter_does_not_leak_the_asset_boundary() -> None:
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_boundary() -> None:
        async with chat_asset_mutation():
            holder_entered.set()
            await release_holder.wait()

    async def enter_once() -> None:
        async with chat_asset_mutation():
            return

    holder = asyncio.create_task(hold_boundary())
    await holder_entered.wait()
    waiter = asyncio.create_task(enter_once())
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    release_holder.set()
    await holder
    await asyncio.wait_for(enter_once(), timeout=0.5)


@pytest.mark.asyncio
async def test_waiting_for_asset_boundary_does_not_block_the_event_loop() -> None:
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_boundary() -> None:
        async with chat_asset_mutation():
            holder_entered.set()
            await release_holder.wait()

    async def wait_for_boundary() -> None:
        async with chat_asset_mutation():
            return

    holder = asyncio.create_task(hold_boundary())
    await holder_entered.wait()
    waiter = asyncio.create_task(wait_for_boundary())

    heartbeat = asyncio.Event()
    asyncio.get_running_loop().call_soon(heartbeat.set)
    await asyncio.wait_for(heartbeat.wait(), timeout=0.2)
    assert not waiter.done()

    release_holder.set()
    await holder
    await waiter


@pytest.mark.asyncio
async def test_cancelling_threaded_mutation_keeps_boundary_until_worker_stops() -> None:
    mutation_started = threading.Event()
    release_mutation = threading.Event()
    mutation_finished = threading.Event()
    competitor_entered = asyncio.Event()

    def blocking_mutation() -> None:
        mutation_started.set()
        if not release_mutation.wait(2):
            raise TimeoutError("test mutation was not released")
        mutation_finished.set()

    async def compete_for_boundary() -> None:
        async with chat_asset_mutation():
            competitor_entered.set()

    mutation = asyncio.create_task(run_chat_asset_mutation(blocking_mutation))
    await _wait_for_thread_event(mutation_started)
    mutation.cancel()
    competitor = asyncio.create_task(compete_for_boundary())
    await asyncio.sleep(0.05)

    assert not mutation.done()
    assert not competitor_entered.is_set()

    release_mutation.set()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert mutation_finished.is_set()
    await asyncio.wait_for(competitor_entered.wait(), timeout=0.5)
    await competitor


@pytest.mark.asyncio
async def test_ordinary_user_turn_is_not_serialized_by_asset_boundary(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(
        db_path=str(runtime_paths_with_schema.chat_db_path),
        runtime_paths=runtime_paths_with_schema,
    )
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_boundary() -> None:
        async with chat_asset_mutation():
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_boundary())
    await holder_entered.wait()
    message = await asyncio.wait_for(
        store.create_user_turn(
            session_id="session-plain",
            user_id="user-1",
            turn_id="turn-plain",
            message_text="plain text",
            created_at_ms=100,
        ),
        timeout=0.5,
    )

    assert message.turn_id == "turn-plain"
    release_holder.set()
    await holder
    await store.shutdown()


@pytest.mark.asyncio
async def test_owner_commit_wins_before_gc_and_preserves_asset(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    ingestion = LocalChatAttachmentIngestionService(runtime_paths=paths)
    attachment = await run_chat_asset_mutation(
        ingestion.ingest_attachment,
        session_id="session-send-first",
        turn_id="turn-send-first",
        original_name="notes.txt",
        content=b"keep",
        mime_type="text/plain",
    )
    attachment_path = Path(str(attachment["storage_path"]))
    os.utime(attachment_path, (0, 0))
    gc = ChatAssetGC(runtime_paths=paths, now=lambda: 10**12)
    owner_write_entered = asyncio.Event()
    release_owner_write = asyncio.Event()
    original_replace = store._replace_message_attachments

    async def blocked_replace(*args, **kwargs) -> None:
        owner_write_entered.set()
        await release_owner_write.wait()
        await original_replace(*args, **kwargs)

    monkeypatch.setattr(store, "_replace_message_attachments", blocked_replace)
    send = asyncio.create_task(
        store.create_user_turn(
            session_id="session-send-first",
            user_id="user-1",
            turn_id="turn-send-first",
            message_text="attached",
            attachment_payloads=[attachment],
            created_at_ms=100,
        )
    )
    await owner_write_entered.wait()
    sweep = asyncio.create_task(
        run_chat_asset_mutation(
            gc.sweep_orphan_assets,
            orphan_grace_hours=0,
        )
    )
    await asyncio.sleep(0.05)
    assert not sweep.done()

    release_owner_write.set()
    await send
    result = await sweep

    assert result["chat_asset_orphan_files_deleted"] == 0
    assert attachment_path.is_file()
    with sqlite3.connect(paths.chat_db_path) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_message_asset_refs
            WHERE asset_key LIKE '%/turn-send-first/%'
              AND asset_kind = 'attachment'
            """
        ).fetchone()[0] == 1
    await store.shutdown()


@pytest.mark.asyncio
async def test_gc_snapshot_wins_before_owner_commit_and_send_rolls_back(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    await store.create_user_turn(
        session_id="session-gc-first",
        user_id="user-1",
        turn_id="turn-seed",
        message_text="seed",
        created_at_ms=10,
    )
    ingestion = LocalChatAttachmentIngestionService(runtime_paths=paths)
    attachment = await run_chat_asset_mutation(
        ingestion.ingest_attachment,
        session_id="session-gc-first",
        turn_id="turn-gc-first",
        original_name="notes.txt",
        content=b"stale",
        mime_type="text/plain",
    )
    attachment_path = Path(str(attachment["storage_path"]))
    os.utime(attachment_path, (0, 0))
    gc = ChatAssetGC(runtime_paths=paths, now=lambda: 10**12)
    snapshot_taken = threading.Event()
    release_snapshot = threading.Event()
    original_snapshot = gc._active_asset_scopes

    def blocked_snapshot():
        result = original_snapshot()
        snapshot_taken.set()
        if not release_snapshot.wait(2):
            raise TimeoutError("test GC snapshot was not released")
        return result

    monkeypatch.setattr(gc, "_active_asset_scopes", blocked_snapshot)
    sweep = asyncio.create_task(
        run_chat_asset_mutation(
            gc.sweep_orphan_assets,
            orphan_grace_hours=0,
        )
    )
    await _wait_for_thread_event(snapshot_taken)
    send = asyncio.create_task(
        store.create_user_turn(
            session_id="session-gc-first",
            user_id="user-1",
            turn_id="turn-gc-first",
            message_text="attached",
            attachment_payloads=[attachment],
            created_at_ms=100,
        )
    )
    await asyncio.sleep(0.05)
    assert not send.done()

    release_snapshot.set()
    result = await sweep
    with pytest.raises(ChatAssetOwnershipError):
        await send

    assert result["chat_asset_orphan_files_deleted"] == 1
    assert not attachment_path.exists()
    with sqlite3.connect(paths.chat_db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_turns WHERE turn_id = 'turn-gc-first'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE turn_id = 'turn-gc-first'"
        ).fetchone()[0] == 0
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_message_asset_refs
            WHERE asset_key LIKE '%/turn-gc-first/%'
            """
        ).fetchone()[0] == 0
    await store.shutdown()


@pytest.mark.asyncio
async def test_upload_publishes_no_half_file_and_gc_waits(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.core.chat_assets import io as asset_io

    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    await store.create_user_turn(
        session_id="session-upload",
        user_id="user-1",
        turn_id="turn-seed",
        message_text="seed",
        created_at_ms=10,
    )
    replace_started = threading.Event()
    release_replace = threading.Event()
    target_paths: list[Path] = []
    original_replace = asset_io.os.replace

    def blocked_replace(source, target) -> None:
        target_paths.append(Path(target))
        replace_started.set()
        if not release_replace.wait(2):
            raise TimeoutError("test atomic publish was not released")
        original_replace(source, target)

    monkeypatch.setattr(asset_io.os, "replace", blocked_replace)
    ingestion = LocalChatAttachmentIngestionService(runtime_paths=paths)
    upload = asyncio.create_task(
        run_chat_asset_mutation(
            ingestion.ingest_attachment,
            session_id="session-upload",
            turn_id="turn-upload",
            original_name="notes.txt",
            content=b"complete bytes",
            mime_type="text/plain",
        )
    )
    await _wait_for_thread_event(replace_started)
    assert len(target_paths) == 1
    assert not target_paths[0].exists()
    temporary_files = list(target_paths[0].parent.glob(".*.tmp"))
    assert len(temporary_files) == 1
    assert temporary_files[0].read_bytes() == b"complete bytes"

    sweep = asyncio.create_task(
        run_chat_asset_mutation(
            ChatAssetGC(runtime_paths=paths).sweep_orphan_assets,
            orphan_grace_hours=0,
        )
    )
    await asyncio.sleep(0.05)
    assert not sweep.done()

    release_replace.set()
    attachment = await upload
    await sweep

    assert Path(str(attachment["storage_path"])).read_bytes() == b"complete bytes"
    assert not list(target_paths[0].parent.glob(".*.tmp"))
    await store.shutdown()


@pytest.mark.asyncio
async def test_atomic_publish_failure_leaves_no_managed_file_or_temporary(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.core.chat_assets import io as asset_io

    paths = runtime_paths_with_schema

    def fail_replace(_source, _target) -> None:
        raise OSError("simulated atomic publish failure")

    monkeypatch.setattr(asset_io.os, "replace", fail_replace)
    ingestion = LocalChatAttachmentIngestionService(runtime_paths=paths)

    with pytest.raises(OSError, match="simulated atomic publish failure"):
        await run_chat_asset_mutation(
            ingestion.ingest_attachment,
            session_id="session-failed-upload",
            turn_id="turn-failed-upload",
            original_name="notes.txt",
            content=b"never visible",
            mime_type="text/plain",
        )

    target_dir = paths.chat_files_dir / "session-failed-upload" / "turn-failed-upload"
    assert not [path for path in target_dir.glob("*") if path.is_file()]
    assert not list(target_dir.glob(".*.tmp"))


@pytest.mark.asyncio
async def test_each_owner_write_path_claims_managed_assets(
    runtime_paths_with_schema,
) -> None:
    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    ingestion = LocalChatAttachmentIngestionService(runtime_paths=paths)

    user_attachment = await run_chat_asset_mutation(
        ingestion.ingest_attachment,
        session_id="session-owner-paths",
        turn_id="turn-user-owner",
        original_name="user.txt",
        content=b"user",
        mime_type="text/plain",
    )
    user_message = await store.create_user_turn(
        session_id="session-owner-paths",
        user_id="user-1",
        turn_id="turn-user-owner",
        message_text="user",
        attachment_payloads=[user_attachment],
        created_at_ms=100,
    )

    appended_attachment = await run_chat_asset_mutation(
        ingestion.ingest_attachment,
        session_id="session-owner-paths",
        turn_id="turn-user-owner",
        original_name="append.txt",
        content=b"append",
        mime_type="text/plain",
    )
    appended_message = ChatMessageRecord(
        message_id="message-appended-owner",
        session_id="session-owner-paths",
        turn_id="turn-user-owner",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_rhythm_segment",
        content_text="append",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=110,
        sequence_no=2,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    await store.append_message(
        appended_message,
        attachment_payloads=[appended_attachment],
    )

    await store.create_user_turn(
        session_id="session-owner-paths",
        user_id="user-1",
        turn_id="turn-outcome-owner",
        message_text="outcome",
        created_at_ms=200,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-outcome-owner",
        delivery_attempt_no=0,
        command_id=7,
        updated_at_ms=210,
    )
    outcome_attachment = await run_chat_asset_mutation(
        ingestion.ingest_attachment,
        session_id="session-owner-paths",
        turn_id="turn-outcome-owner",
        original_name="outcome.txt",
        content=b"outcome",
        mime_type="text/plain",
    )
    outcome_message = ChatMessageRecord(
        message_id="message-outcome-owner",
        session_id="session-owner-paths",
        turn_id="turn-outcome-owner",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_final",
        content_text="outcome",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=220,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    committed = await store.commit_user_turn_assistant_outcome(
        turn_id="turn-outcome-owner",
        delivery_attempt_no=0,
        command_id=7,
        messages=[outcome_message],
        attachment_payloads_by_message_id={
            outcome_message.message_id: [outcome_attachment],
        },
        trace_id=None,
        execution_mode="direct",
        ux_plan=None,
        response_mode="final_only",
        started_at_ms=211,
        completed_at_ms=220,
        run_id=None,
        run_revision=0,
        run_disposition="root",
    )

    assert committed is not None
    with sqlite3.connect(paths.chat_db_path) as conn:
        owners = {
            str(row[0])
            for row in conn.execute(
                """
                SELECT DISTINCT message_id
                FROM chat_message_asset_refs
                WHERE message_id IN (?, ?, ?)
                """,
                (
                    user_message.message_id,
                    appended_message.message_id,
                    outcome_message.message_id,
                ),
            ).fetchall()
        }
    assert owners == {
        user_message.message_id,
        appended_message.message_id,
        outcome_message.message_id,
    }
    await store.shutdown()


@pytest.mark.parametrize(
    "replacement_payloads",
    [
        [],
        [
            {
                "kind": "mcp_resource",
                "attachment_id": "mcp-reference",
                "server_id": "server-1",
                "uri": "memory://reference",
            }
        ],
    ],
    ids=("empty", "mcp-only"),
)
@pytest.mark.asyncio
async def test_explicit_attachment_replacement_clears_old_owner_and_gc_reclaims_file(
    runtime_paths_with_schema,
    replacement_payloads: list[dict[str, object]],
) -> None:
    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    attachment = await run_chat_asset_mutation(
        LocalChatAttachmentIngestionService(
            runtime_paths=paths,
        ).ingest_attachment,
        session_id="session-replace-owner",
        turn_id="turn-replace-owner",
        original_name="old.txt",
        content=b"old owner",
        mime_type="text/plain",
    )
    message = await store.create_user_turn(
        session_id="session-replace-owner",
        user_id="user-1",
        turn_id="turn-replace-owner",
        message_text="old",
        attachment_payloads=[attachment],
        created_at_ms=100,
    )
    replacement_record = replace(
        message,
        payload_json=json.dumps(
            {"attachments": replacement_payloads},
            ensure_ascii=False,
        ),
    )

    await store.append_message(
        replacement_record,
        attachment_payloads=replacement_payloads,
    )

    with sqlite3.connect(paths.chat_db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE message_id = ?",
            (message.message_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_message_asset_refs WHERE message_id = ?",
            (message.message_id,),
        ).fetchone()[0] == 0
    attachment_path = Path(str(attachment["storage_path"]))
    os.utime(attachment_path, (0, 0))
    result = await run_chat_asset_mutation(
        ChatAssetGC(runtime_paths=paths, now=lambda: 10**12).sweep_orphan_assets,
        orphan_grace_hours=0,
    )

    assert result["chat_asset_orphan_files_deleted"] == 1
    assert not attachment_path.exists()
    await store.shutdown()


@pytest.mark.asyncio
async def test_idempotent_user_turn_retry_with_empty_payload_cannot_clear_owner(
    runtime_paths_with_schema,
) -> None:
    from magi.chat.store import ChatTurnConflictError

    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    attachment = await run_chat_asset_mutation(
        LocalChatAttachmentIngestionService(
            runtime_paths=paths,
        ).ingest_attachment,
        session_id="session-idempotent-owner",
        turn_id="turn-idempotent-owner",
        original_name="kept.txt",
        content=b"kept",
        mime_type="text/plain",
    )
    message = await store.create_user_turn(
        session_id="session-idempotent-owner",
        user_id="user-1",
        turn_id="turn-idempotent-owner",
        message_text="kept",
        attachment_payloads=[attachment],
        created_at_ms=100,
    )

    with pytest.raises(ChatTurnConflictError):
        await store.create_user_turn_once(
            session_id="session-idempotent-owner",
            user_id="user-1",
            turn_id="turn-idempotent-owner",
            message_text="kept",
            attachment_payloads=[],
            created_at_ms=100,
        )

    with sqlite3.connect(paths.chat_db_path) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_message_asset_refs
            WHERE message_id = ?
              AND asset_kind = 'attachment'
            """,
            (message.message_id,),
        ).fetchone()[0] == 1
    assert Path(str(attachment["storage_path"])).is_file()
    await store.shutdown()


@pytest.mark.asyncio
async def test_explicit_empty_outcome_attachment_map_uses_asset_boundary(
    runtime_paths_with_schema,
) -> None:
    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    await store.create_user_turn(
        session_id="session-empty-outcome",
        user_id="user-1",
        turn_id="turn-empty-outcome",
        message_text="answer",
        created_at_ms=100,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-empty-outcome",
        delivery_attempt_no=0,
        command_id=17,
        updated_at_ms=110,
    )
    outcome = ChatMessageRecord(
        message_id="message-empty-outcome",
        session_id="session-empty-outcome",
        turn_id="turn-empty-outcome",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_final",
        content_text="done",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=120,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_boundary() -> None:
        async with chat_asset_mutation():
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_boundary())
    await holder_entered.wait()
    commit = asyncio.create_task(
        store.commit_user_turn_assistant_outcome(
            turn_id="turn-empty-outcome",
            delivery_attempt_no=0,
            command_id=17,
            messages=[outcome],
            attachment_payloads_by_message_id={outcome.message_id: []},
            trace_id=None,
            execution_mode="direct",
            ux_plan=None,
            response_mode="final_only",
            started_at_ms=111,
            completed_at_ms=120,
            run_id=None,
            run_revision=0,
            run_disposition="root",
        )
    )
    await asyncio.sleep(0.05)
    assert not commit.done()

    release_holder.set()
    await holder
    assert await commit is not None
    await store.shutdown()


@pytest.mark.asyncio
async def test_no_attachment_outcome_is_not_serialized_by_asset_boundary(
    runtime_paths_with_schema,
) -> None:
    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    await store.create_user_turn(
        session_id="session-plain-outcome",
        user_id="user-1",
        turn_id="turn-plain-outcome",
        message_text="answer",
        created_at_ms=100,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-plain-outcome",
        delivery_attempt_no=0,
        command_id=18,
        updated_at_ms=110,
    )
    outcome = ChatMessageRecord(
        message_id="message-plain-outcome",
        session_id="session-plain-outcome",
        turn_id="turn-plain-outcome",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_final",
        content_text="done",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=120,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_boundary() -> None:
        async with chat_asset_mutation():
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_boundary())
    await holder_entered.wait()
    committed = await asyncio.wait_for(
        store.commit_user_turn_assistant_outcome(
            turn_id="turn-plain-outcome",
            delivery_attempt_no=0,
            command_id=18,
            messages=[outcome],
            attachment_payloads_by_message_id={outcome.message_id: None},
            trace_id=None,
            execution_mode="direct",
            ux_plan=None,
            response_mode="final_only",
            started_at_ms=111,
            completed_at_ms=120,
            run_id=None,
            run_revision=0,
            run_disposition="root",
        ),
        timeout=0.5,
    )

    assert committed is not None
    release_holder.set()
    await holder
    await store.shutdown()


@pytest.mark.asyncio
async def test_invalid_attachment_replacement_rolls_back_without_losing_owner(
    runtime_paths_with_schema,
    tmp_path: Path,
) -> None:
    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    attachment = await run_chat_asset_mutation(
        LocalChatAttachmentIngestionService(
            runtime_paths=paths,
        ).ingest_attachment,
        session_id="session-invalid-replace",
        turn_id="turn-invalid-replace",
        original_name="kept.txt",
        content=b"kept",
        mime_type="text/plain",
    )
    message = await store.create_user_turn(
        session_id="session-invalid-replace",
        user_id="user-1",
        turn_id="turn-invalid-replace",
        message_text="kept",
        attachment_payloads=[attachment],
        created_at_ms=100,
    )
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")

    with pytest.raises(ChatAssetOwnershipError):
        await store.append_message(
            replace(message, payload_json='{"attachments":[]}'),
            attachment_payloads=[
                {
                    **attachment,
                    "storage_path": str(outside),
                }
            ],
        )

    with sqlite3.connect(paths.chat_db_path) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_message_asset_refs
            WHERE message_id = ?
              AND asset_kind = 'attachment'
            """,
            (message.message_id,),
        ).fetchone()[0] == 1
        payload_json = conn.execute(
            "SELECT payload_json FROM chat_messages WHERE message_id = ?",
            (message.message_id,),
        ).fetchone()[0]
    assert json.loads(payload_json)["attachments"][0]["attachment_id"] == attachment[
        "attachment_id"
    ]
    assert Path(str(attachment["storage_path"])).is_file()
    await store.shutdown()


@pytest.mark.asyncio
async def test_attachment_read_rejects_soft_deleted_session(
    runtime_paths_with_schema,
) -> None:
    from magi.chat.read_service import ChatReadService

    paths = runtime_paths_with_schema
    store = ChatStore(db_path=str(paths.chat_db_path), runtime_paths=paths)
    attachment = await run_chat_asset_mutation(
        LocalChatAttachmentIngestionService(
            runtime_paths=paths,
        ).ingest_attachment,
        session_id="session-soft-deleted",
        turn_id="turn-soft-deleted",
        original_name="private.txt",
        content=b"private",
        mime_type="text/plain",
    )
    await store.create_user_turn(
        session_id="session-soft-deleted",
        user_id="user-1",
        turn_id="turn-soft-deleted",
        message_text="private",
        attachment_payloads=[attachment],
        created_at_ms=100,
    )
    read_service = ChatReadService()
    read_service._runtime_paths = paths
    read_service._chat_db_path = paths.chat_db_path

    assert (
        read_service.get_attachment_payload(
            "user-1",
            "session-soft-deleted",
            str(attachment["attachment_id"]),
        )
        is not None
    )
    read_service._get_conn().execute(
        """
        UPDATE chat_sessions
        SET deleted_at_ms = ?
        WHERE session_id = ?
        """,
        (200, "session-soft-deleted"),
    )
    read_service._get_conn().commit()

    assert (
        read_service.get_attachment_payload(
            "user-1",
            "session-soft-deleted",
            str(attachment["attachment_id"]),
        )
        is None
    )
    read_service.close()
    await store.shutdown()


@pytest.mark.parametrize("operation", ("delete-session", "clear-all"))
@pytest.mark.asyncio
async def test_cancelled_destructive_read_keeps_asset_boundary_until_thread_stops(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    from magi.chat.read_service import ChatReadService

    service = ChatReadService()
    mutation_started = threading.Event()
    release_mutation = threading.Event()
    mutation_finished = threading.Event()
    competitor_entered = asyncio.Event()

    def blocking_mutation(*_args) -> int:
        mutation_started.set()
        if not release_mutation.wait(2):
            raise TimeoutError("test destructive mutation was not released")
        mutation_finished.set()
        return 0

    monkeypatch.setattr(service, "_run_isolated", blocking_mutation)

    async def invoke() -> object:
        if operation == "delete-session":
            return await service.adelete_session("user-1", "session-1")
        return await service.aclear_all_sessions()

    async def compete_for_boundary() -> None:
        async with chat_asset_mutation():
            competitor_entered.set()

    destructive = asyncio.create_task(invoke())
    await _wait_for_thread_event(mutation_started)
    destructive.cancel()
    competitor = asyncio.create_task(compete_for_boundary())
    await asyncio.sleep(0.05)

    assert not destructive.done()
    assert not competitor_entered.is_set()
    release_mutation.set()
    with pytest.raises(asyncio.CancelledError):
        await destructive
    assert mutation_finished.is_set()
    await asyncio.wait_for(competitor_entered.wait(), timeout=0.5)
    await competitor
    service.close()
