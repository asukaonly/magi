from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from alembic import command
import pytest

from _shared.sqlite_privacy import assert_sqlite_fragment_absent, sqlite_fragment_present
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.events.contracts import RuntimeCommandType, SourceSyncCommand
from magi.events.lifecycle import RuntimeCommandQueueModule
from magi.events.runtime_queue import (
    FullUserContentClearConflictError,
    SQLiteRuntimeCommandQueue,
)


def _prepare_queue(db_path: Path) -> SQLiteRuntimeCommandQueue:
    target = next(item for item in MIGRATION_TARGETS if item.name == "message_queue")
    command.upgrade(_build_config(target, db_path), "head")
    return SQLiteRuntimeCommandQueue(db_path=str(db_path))


@pytest.mark.asyncio
async def test_backend_clear_state_survives_restart_then_returns_to_idle(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "message-queue.db"
    queue = _prepare_queue(db_path)
    await queue.start()

    await queue.begin_full_user_content_clear("clear-restart-transaction")
    assert sqlite_fragment_present(db_path, "clear-restart-transaction")
    pending = await queue.read_full_user_content_clear_state()
    assert pending.status == "pending"
    assert pending.transaction_id == "clear-restart-transaction"
    await queue.stop()

    reopened = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await reopened.start()
    assert (await reopened.read_full_user_content_clear_state()).status == "pending"
    await reopened.complete_full_user_content_clear(
        transaction_id="clear-restart-transaction",
    )
    idle = await reopened.read_full_user_content_clear_state()
    assert idle.status == "idle"
    assert idle.transaction_id is None
    assert idle.started_at is None
    assert_sqlite_fragment_absent(db_path, "clear-restart-transaction")
    await reopened.stop()


@pytest.mark.asyncio
async def test_same_transaction_can_restart_after_success_without_residue(
    tmp_path: Path,
) -> None:
    queue = _prepare_queue(tmp_path / "message-queue.db")
    await queue.start()
    await queue.begin_full_user_content_clear("clear-repeat-transaction")
    await queue.complete_full_user_content_clear(
        transaction_id="clear-repeat-transaction",
    )

    idle = await queue.read_full_user_content_clear_state()
    assert idle.status == "idle"
    assert idle.transaction_id is None

    await queue.begin_full_user_content_clear("clear-repeat-transaction")

    state = await queue.read_full_user_content_clear_state()
    assert state.status == "pending"
    await queue.stop()


@pytest.mark.asyncio
async def test_pending_transaction_rejects_a_different_desktop_owner(
    tmp_path: Path,
) -> None:
    queue = _prepare_queue(tmp_path / "message-queue.db")
    await queue.start()
    await queue.begin_full_user_content_clear("clear-first-transaction")

    with pytest.raises(FullUserContentClearConflictError):
        await queue.begin_full_user_content_clear("clear-second-transaction")
    with pytest.raises(RuntimeError, match="not pending"):
        await queue.complete_full_user_content_clear(
            transaction_id="clear-second-transaction",
        )

    state = await queue.read_full_user_content_clear_state()
    assert state.status == "pending"
    assert state.transaction_id == "clear-first-transaction"
    await queue.stop()


@pytest.mark.asyncio
async def test_transaction_identifier_is_bounded_and_content_free(
    tmp_path: Path,
) -> None:
    queue = _prepare_queue(tmp_path / "message-queue.db")
    await queue.start()

    for invalid in ("", "short", "contains/private/path", "contains space"):
        with pytest.raises(ValueError, match="transaction ID is invalid"):
            await queue.begin_full_user_content_clear(invalid)

    assert (await queue.read_full_user_content_clear_state()).status == "idle"
    await queue.stop()


@pytest.mark.asyncio
async def test_host_marker_is_adopted_before_claimed_command_recovery(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path),
    )
    await queue.start()
    command_id = await queue.enqueue_source_sync(
        SourceSyncCommand(source="test", connection_id="account-main", source_name="history")
    )
    claimed = await queue.claim_next(
        consumer_name="crashed-worker",
        command_types=(RuntimeCommandType.SOURCE_SYNC,),
    )
    assert claimed is not None
    assert claimed.command_id == command_id
    assert (await queue.read_full_user_content_clear_state()).status == "idle"
    await queue.stop()

    transaction_id = "clear-host-marker-before-api"
    monkeypatch.setenv("MAGI_FULL_DATA_CLEAR_TRANSACTION_ID", transaction_id)
    recover_claimed = AsyncMock(side_effect=AssertionError("claimed commands must stay fenced"))
    monkeypatch.setattr(
        SQLiteRuntimeCommandQueue,
        "recover_claimed_commands_after_restart",
        recover_claimed,
    )
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = runtime_paths_with_schema
    module = RuntimeCommandQueueModule(context)

    await module.init()
    try:
        state = (
            await context.runtime_commands.runtime_command_queue.read_full_user_content_clear_state()
        )
        assert state.status == "pending"
        assert state.transaction_id == transaction_id
        assert context.runtime_commands.full_clear_recovery_pending is True
        assert recover_claimed.await_count == 0
        assert (
            await context.runtime_commands.runtime_command_queue.claim_next(
                consumer_name="restarted-worker",
                command_types=(RuntimeCommandType.SOURCE_SYNC,),
            )
            is None
        )
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_pending_backend_state_without_host_owner_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    transaction_id = "clear-owner-marker-was-lost"
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path),
    )
    await queue.start()
    await queue.begin_full_user_content_clear(transaction_id)
    await queue.stop()

    monkeypatch.delenv("MAGI_FULL_DATA_CLEAR_TRANSACTION_ID", raising=False)
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = runtime_paths_with_schema
    module = RuntimeCommandQueueModule(context)

    with pytest.raises(RuntimeError, match="requires its desktop owner marker"):
        await module.init()

    assert context.runtime_commands.runtime_command_queue is None
    assert context.runtime_commands.full_clear_recovery_pending is False
    reopened = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path),
    )
    await reopened.start()
    state = await reopened.read_full_user_content_clear_state()
    assert state.status == "pending"
    assert state.transaction_id == transaction_id
    await reopened.stop()
