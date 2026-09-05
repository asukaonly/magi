from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_destructive_chat_and_global_clear_cannot_deadlock_on_reversed_inner_locks(
    tmp_path: Path,
) -> None:
    import asyncio

    from magi.core.operation_barrier import AsyncOperationBarrier
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    memory_barrier = AsyncOperationBarrier()
    chat_holds_memory = asyncio.Event()
    global_started = asyncio.Event()
    order: list[str] = []

    async def chat_delete() -> None:
        async with queue.user_message_destructive_operation():
            async with memory_barrier.operation():
                chat_holds_memory.set()
                await global_started.wait()
                await asyncio.sleep(0)
                async with queue.user_message_clear_boundary():
                    order.append("chat")

    async def global_clear() -> None:
        await chat_holds_memory.wait()
        global_started.set()
        async with queue.user_message_global_clear_boundary():
            async with memory_barrier.exclusive():
                order.append("global")

    await asyncio.wait_for(
        asyncio.gather(chat_delete(), global_clear()),
        timeout=1.0,
    )

    assert order == ["chat", "global"]


@pytest.mark.asyncio
async def test_runtime_command_queue_enqueues_and_claims_user_message(tmp_path: Path) -> None:
    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    try:
        queued_command_id = await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="hello",
                runtime_namespace="desktop",
                metadata={"origin": "test"},
            )
        )

        claimed = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )

        assert claimed is not None
        assert claimed.command_id == queued_command_id
        assert claimed.command_type is RuntimeCommandType.USER_MESSAGE
        assert claimed.payload["message"] == "hello"

        await queue.ack(claimed.command_id)

        stats = await queue.get_stats()
        assert stats["pending_count"] == 0
        assert stats["claimed_count"] == 0
        assert stats["completed_count"] == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_recovers_prior_process_claim_immediately_on_start(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    db_path = tmp_path / "runtime_commands.db"
    first_queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await first_queue.start()
    command_id = await first_queue.enqueue_user_message(
        UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            message="recover immediately",
        )
    )
    claimed = await first_queue.claim_next(
        consumer_name="old-process",
        command_types=(RuntimeCommandType.USER_MESSAGE,),
    )
    assert claimed is not None
    assert claimed.command_id == command_id
    await first_queue.stop()

    restarted_queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await restarted_queue.start()
    try:
        recovered = await restarted_queue.claim_next(
            consumer_name="new-process",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert recovered is not None
        assert recovered.command_id == command_id
        assert recovered.retry_count == 1
        with sqlite3.connect(db_path) as conn:
            assert conn.execute(
                "SELECT last_error FROM runtime_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone() == ("PROCESS_RESTART_RECOVERY",)
    finally:
        await restarted_queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_recovers_expired_claim_lease(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    db_path = tmp_path / "runtime_commands.db"
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(db_path),
        claim_lease_seconds=0.001,
    )
    await queue.start()
    command_id = await queue.enqueue_user_message(
        UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            message="recover expired lease",
        )
    )
    first = await queue.claim_next(
        consumer_name="stuck-worker",
        command_types=(RuntimeCommandType.USER_MESSAGE,),
    )
    assert first is not None
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE runtime_commands SET claimed_at = 0 WHERE command_id = ?",
            (command_id,),
        )
        conn.commit()

    try:
        recovered = await queue.claim_next(
            consumer_name="recovery-worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert recovered is not None
        assert recovered.command_id == command_id
        assert recovered.retry_count == 1
        with sqlite3.connect(db_path) as conn:
            assert conn.execute(
                "SELECT last_error FROM runtime_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone() == ("CLAIM_LEASE_EXPIRED",)
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_deduplicates_stable_user_turn_correlation(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    command = UserMessageCommand(
        source="api",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        message="hello",
        correlation_id="user_turn:turn-1",
        created_at=1710000000.0,
    )
    try:
        first_id = await queue.enqueue_user_message(command)
        second_id = await queue.enqueue_user_message(command)

        assert second_id == first_id
        stats = await queue.get_stats()
        assert stats["pending_count"] == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_schedules_user_message_attempts_monotonically(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import UserMessageCommand
    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        UserMessageScheduleOutcome,
    )

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    def _command(attempt_no: int) -> UserMessageCommand:
        return UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            message="same logical turn",
            correlation_id="user_message:message-1",
            created_at=1710000000.0,
            delivery_attempt_no=attempt_no,
        )

    try:
        first = await queue.schedule_user_message(_command(0))
        duplicate = await queue.schedule_user_message(_command(0))
        newer = await queue.schedule_user_message(_command(1))
        stale = await queue.schedule_user_message(_command(0))

        assert first.outcome is UserMessageScheduleOutcome.SCHEDULED
        assert first.current_attempt_no == 0
        assert duplicate.outcome is UserMessageScheduleOutcome.EXISTING
        assert duplicate.command_id == first.command_id
        assert newer.outcome is UserMessageScheduleOutcome.SCHEDULED
        assert newer.current_attempt_no == 1
        assert newer.command_id != first.command_id
        assert stale.outcome is UserMessageScheduleOutcome.STALE
        assert stale.current_attempt_no == 1
        assert stale.command_id == newer.command_id

        with sqlite3.connect(queue.db_path) as conn:
            rows = conn.execute(
                """
                SELECT command_id, delivery_attempt_no, status
                FROM runtime_commands
                WHERE correlation_id = ?
                ORDER BY command_id
                """,
                ("user_message:message-1",),
            ).fetchall()
            receipt = conn.execute(
                """
                SELECT current_attempt_no, current_command_id, delivery_status
                FROM runtime_user_message_idempotency
                WHERE correlation_id = ?
                """,
                ("user_message:message-1",),
            ).fetchone()
        assert rows == [
            (first.command_id, 0, "completed"),
            (newer.command_id, 1, "pending"),
        ]
        assert receipt == (1, newer.command_id, "open")
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_rejects_stale_attempt_from_enqueue_api(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import UserMessageCommand
    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        StaleUserMessageDeliveryAttemptError,
    )

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    def _command(attempt_no: int) -> UserMessageCommand:
        return UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            message="same logical turn",
            correlation_id="user_message:message-1",
            delivery_attempt_no=attempt_no,
            created_at=1710000000.0,
        )

    try:
        await queue.enqueue_user_message(_command(1))
        with pytest.raises(StaleUserMessageDeliveryAttemptError):
            await queue.enqueue_user_message(_command(0))
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_rejects_same_correlation_for_different_input(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    try:
        await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="hello",
                correlation_id="user_turn:turn-1",
                created_at=1710000000.0,
            )
        )
        with pytest.raises(
            ValueError,
            match="correlation id was reused for different input",
        ):
            await queue.enqueue_user_message(
                UserMessageCommand(
                    source="api",
                    user_id="user-1",
                    session_id="session-1",
                    turn_id="turn-1",
                    message="different",
                    correlation_id="user_turn:turn-1",
                    created_at=1710000000.0,
                )
            )
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_user_message_idempotency_survives_completed_command_gc(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        UserMessageScheduleOutcome,
    )

    db_path = tmp_path / "runtime_commands.db"
    queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await queue.start()
    original = UserMessageCommand(
        source="api",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        message="hello",
        correlation_id="user_message:message-1",
        created_at=1710000000.0,
    )
    try:
        first_id = await queue.enqueue_user_message(original)
        claimed = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert claimed is not None
        await queue.ack(claimed.command_id)
        with sqlite3.connect(db_path) as db:
            db.execute("DELETE FROM runtime_commands WHERE command_id = ?", (first_id,))
            db.commit()

        same_attempt = await queue.schedule_user_message(original)
        assert same_attempt.outcome is UserMessageScheduleOutcome.EXISTING
        assert same_attempt.command_id == first_id
        assert (await queue.get_stats())["pending_count"] == 0

        next_attempt = await queue.schedule_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="hello",
                correlation_id="user_message:message-1",
                created_at=1710000000.0,
                delivery_attempt_no=1,
            )
        )
        assert next_attempt.outcome is UserMessageScheduleOutcome.SCHEDULED
        assert next_attempt.command_id != first_id
        assert (await queue.get_stats())["pending_count"] == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_stale_ack_and_requeue_do_not_change_current_user_message_attempt(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    def _command(attempt_no: int) -> UserMessageCommand:
        return UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            message="same logical turn",
            correlation_id="user_message:message-1",
            created_at=1710000000.0,
            delivery_attempt_no=attempt_no,
        )

    try:
        old_id = await queue.enqueue_user_message(_command(0))
        old_claim = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert old_claim is not None
        assert old_claim.command_id == old_id

        current = await queue.schedule_user_message(_command(1))
        assert current.command_id is not None
        await queue.requeue(old_id, error_text="OLD_HANDLER_FAILED")
        await queue.ack(old_id)

        with sqlite3.connect(queue.db_path) as conn:
            receipt = conn.execute(
                """
                SELECT current_attempt_no, current_command_id, delivery_status
                FROM runtime_user_message_idempotency
                WHERE correlation_id = ?
                """,
                ("user_message:message-1",),
            ).fetchone()
            old_row = conn.execute(
                "SELECT status FROM runtime_commands WHERE command_id = ?",
                (old_id,),
            ).fetchone()
        assert receipt == (1, current.command_id, "open")
        assert old_row == ("completed",)

        claimed_current = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert claimed_current is not None
        assert claimed_current.command_id == current.command_id
        assert claimed_current.delivery_attempt_no == 1
        assert claimed_current.as_user_message().delivery_attempt_no == 1
        assert (
            claimed_current.as_user_message().runtime_command_id
            == claimed_current.command_id
        )
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_enqueues_and_claims_llm_refresh(tmp_path: Path) -> None:
    from magi.events.contracts import RefreshLLMConfigCommand, RuntimeCommandType
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    try:
        queued_command_id = await queue.enqueue_refresh_llm_config(
            RefreshLLMConfigCommand(
                source="api",
                reason="settings_saved",
            )
        )

        claimed = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.REFRESH_LLM_CONFIG,),
        )

        assert claimed is not None
        assert claimed.command_id == queued_command_id
        assert claimed.command_type is RuntimeCommandType.REFRESH_LLM_CONFIG
        assert claimed.payload["source"] == "api"
        assert claimed.payload["reason"] == "settings_saved"

        await queue.ack(claimed.command_id)

        stats = await queue.get_stats()
        assert stats["pending_count"] == 0
        assert stats["claimed_count"] == 0
        assert stats["completed_count"] == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_enqueues_and_claims_source_sync(tmp_path: Path) -> None:
    from magi.events.contracts import RuntimeCommandType, SourceSyncCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    try:
        queued_command_id = await queue.enqueue_source_sync(
            SourceSyncCommand(
                source="api",
                connection_id="account-main",
                source_name="calendar",
            )
        )

        claimed = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.SOURCE_SYNC,),
        )

        assert claimed is not None
        assert claimed.command_id == queued_command_id
        assert claimed.command_type is RuntimeCommandType.SOURCE_SYNC
        assert claimed.payload["source_name"] == "calendar"
        assert claimed.as_source_sync().connection_id == "account-main"
        assert claimed.payload["first_context"] is False

        await queue.ack(claimed.command_id)

        stats = await queue.get_stats()
        assert stats["pending_count"] == 0
        assert stats["claimed_count"] == 0
        assert stats["completed_count"] == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_enqueues_and_claims_source_state_flush(tmp_path: Path) -> None:
    from magi.events.contracts import RuntimeCommandType, SourceStateFlushCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    try:
        queued_command_id = await queue.enqueue_source_state_flush(
            SourceStateFlushCommand(
                source="api",
                connection_id="account-main",
                source_name="screen_time",
            )
        )

        claimed = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.SOURCE_STATE_FLUSH,),
        )

        assert claimed is not None
        assert claimed.command_id == queued_command_id
        assert claimed.command_type is RuntimeCommandType.SOURCE_STATE_FLUSH
        assert claimed.payload["source_name"] == "screen_time"
        assert claimed.as_source_state_flush().connection_id == "account-main"

        await queue.ack(claimed.command_id)

        stats = await queue.get_stats()
        assert stats["pending_count"] == 0
        assert stats["claimed_count"] == 0
        assert stats["completed_count"] == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_global_clear_purges_every_clear_sensitive_runtime_command(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import (
        RefreshLLMConfigCommand,
        RuntimeCommandType,
        SourceStateFlushCommand,
        SourceSyncCommand,
        UserMessageCommand,
    )
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    try:
        await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="old message",
            )
        )
        await queue.enqueue_source_sync(
            SourceSyncCommand(
                source="api",
                connection_id="account-main",
                source_name="chrome_history",
                sync_mode="backfill",
            )
        )
        await queue.enqueue_source_state_flush(
            SourceStateFlushCommand(
                source="api",
                connection_id="account-main",
                source_name="screen_time",
            )
        )
        refresh_id = await queue.enqueue_refresh_llm_config(
            RefreshLLMConfigCommand(source="api", reason="settings_saved")
        )

        post_clear_enqueue: asyncio.Task[int] | None = None
        async with queue.user_message_global_clear_boundary():
            generation, purged = await queue.advance_user_message_generation_and_purge()
            post_clear_enqueue = asyncio.create_task(
                queue.enqueue_source_sync(
                    SourceSyncCommand(source="api", connection_id="account-main", source_name="calendar")
                )
            )
            await asyncio.sleep(0)
            assert post_clear_enqueue.done() is False

        assert generation == 1
        assert purged == 3
        assert (
            await queue.claim_next(
                consumer_name="runtime-worker",
                command_types=(
                    RuntimeCommandType.USER_MESSAGE,
                    RuntimeCommandType.SOURCE_SYNC,
                    RuntimeCommandType.SOURCE_STATE_FLUSH,
                ),
            )
            is None
        )

        refresh = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.REFRESH_LLM_CONFIG,),
        )
        assert refresh is not None
        assert refresh.command_id == refresh_id

        assert post_clear_enqueue is not None
        await post_clear_enqueue
        post_clear_sync = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.SOURCE_SYNC,),
        )
        assert post_clear_sync is not None
        assert post_clear_sync.user_message_generation == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_concurrent_enqueue_and_claim_do_not_raise(tmp_path: Path) -> None:
    """A producer (enqueue) and several tight claim loops run on ONE queue instance
    in-process — the real shape (the runtime worker polls claim_next while the API
    enqueues). Concurrent write transactions to the same SQLite file must not raise
    "database is locked"; the instance write lock serializes them. Each command must
    be claimed exactly once. Regression for the flaky in-process write contention
    behind test_runtime_command_processor (#88).
    """
    import asyncio

    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    errors: list[str] = []
    claimed: list[int] = []
    stop = False
    total = 150

    async def claimer() -> None:
        while not stop:
            try:
                cmd = await queue.claim_next(
                    consumer_name="worker",
                    command_types=(RuntimeCommandType.USER_MESSAGE,),
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
                await asyncio.sleep(0)
                continue
            if cmd is not None:
                claimed.append(cmd.command_id)
                try:
                    await queue.ack(cmd.command_id)
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))
            await asyncio.sleep(0)

    async def producer() -> None:
        for i in range(total):
            try:
                await queue.enqueue_user_message(
                    UserMessageCommand(
                        source="api",
                        user_id="u",
                        session_id="s",
                        turn_id=f"t{i}",
                        message=f"m{i}",
                        runtime_namespace="desktop",
                        metadata={},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            await asyncio.sleep(0)

    try:
        claimers = [asyncio.create_task(claimer()) for _ in range(4)]
        await producer()
        for _ in range(400):  # generous drain window
            if len(claimed) >= total:
                break
            await asyncio.sleep(0.005)
        stop = True
        for task in claimers:
            task.cancel()
        await asyncio.gather(*claimers, return_exceptions=True)

        assert errors == [], f"concurrent queue writes raised: {errors[:3]}"
        assert len(claimed) == total, f"claimed {len(claimed)} != enqueued {total}"
        assert len(set(claimed)) == total, "a command was claimed more than once"
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_user_message_clear_boundary_purges_every_old_payload_and_preserves_other_commands(
    tmp_path: Path,
) -> None:
    from magi.core.sqlite import sqlite_connection_async
    from magi.events.contracts import (
        RefreshLLMConfigCommand,
        RuntimeCommandType,
        UserMessageCommand,
    )
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    async def _enqueue(message: str) -> int:
        return await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id=f"turn-{message}",
                message=message,
            )
        )

    try:
        await _enqueue("completed secret")
        completed = await queue.claim_next(
            consumer_name="worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert completed is not None
        await queue.ack(completed.command_id)

        await _enqueue("failed secret")
        failed = await queue.claim_next(
            consumer_name="worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert failed is not None
        async with sqlite_connection_async(queue.db_path) as db:
            await db.execute(
                "UPDATE runtime_commands SET status = 'failed' WHERE command_id = ?",
                (failed.command_id,),
            )
            await db.commit()

        await _enqueue("claimed secret")
        claimed = await queue.claim_next(
            consumer_name="worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert claimed is not None
        await _enqueue("pending secret")
        await queue.enqueue_refresh_llm_config(
            RefreshLLMConfigCommand(source="api", reason="keep me")
        )

        private_scope_marker = "private-scope-marker-that-must-not-survive"
        async with queue.user_message_clear_boundary():
            await queue.block_user_message_scope_and_purge(
                user_id=private_scope_marker,
                session_id=private_scope_marker,
                reason="test-clear",
            )
            generation, purged_count = await queue.advance_user_message_generation_and_purge()

        assert generation == 1
        assert purged_count == 4
        async with sqlite_connection_async(queue.db_path) as db:
            async with db.execute(
                "SELECT command_type, payload_json FROM runtime_commands ORDER BY command_id"
            ) as cursor:
                rows = await cursor.fetchall()
            async with db.execute(
                "SELECT COUNT(*) FROM runtime_user_message_idempotency"
            ) as cursor:
                receipt_count = int((await cursor.fetchone())[0])
            async with db.execute(
                "SELECT COUNT(*) FROM runtime_user_message_scope_blocks"
            ) as cursor:
                scope_block_count = int((await cursor.fetchone())[0])
        assert [(row[0], "keep me" in str(row[1])) for row in rows] == [
            (RuntimeCommandType.REFRESH_LLM_CONFIG.value, True)
        ]
        assert all("secret" not in str(row[1]) for row in rows)
        assert receipt_count == 0
        assert scope_block_count == 0
        queue_files = (
            Path(queue.db_path),
            Path(f"{queue.db_path}-wal"),
        )
        assert all(
            private_scope_marker.encode() not in path.read_bytes()
            for path in queue_files
            if path.exists()
        )

        await _enqueue("new generation")
        next_command = await queue.claim_next(
            consumer_name="worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert next_command is not None
        assert next_command.user_message_generation == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_external_message_context_rejects_pre_clear_and_cross_generation_events(
    tmp_path: Path,
) -> None:
    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        StaleExternalUserMessageError,
    )

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    try:
        old_occurred_at_ms = 1
        captured_generation = await queue.capture_external_user_message_context(
            provider_occurred_at_ms=old_occurred_at_ms,
        )
        assert captured_generation == 0

        async with queue.user_message_clear_boundary():
            generation, _ = await queue.advance_user_message_generation_and_purge()
        assert generation == 1

        with pytest.raises(StaleExternalUserMessageError):
            async with queue.external_user_message_operation(
                provider_occurred_at_ms=old_occurred_at_ms,
                captured_generation=captured_generation,
            ):
                pass
        with pytest.raises(StaleExternalUserMessageError):
            await queue.capture_external_user_message_context(
                provider_occurred_at_ms=old_occurred_at_ms,
            )

        with sqlite3.connect(queue.db_path) as conn:
            cleared_at_ms = int(
                float(
                    conn.execute(
                        "SELECT updated_at FROM runtime_user_message_clear_state "
                        "WHERE singleton_id = 1"
                    ).fetchone()[0]
                )
                * 1000
            )
        current_generation = await queue.capture_external_user_message_context(
            provider_occurred_at_ms=cleared_at_ms + 1,
        )
        assert current_generation == generation
        async with queue.external_user_message_operation(
            provider_occurred_at_ms=cleared_at_ms + 1,
            captured_generation=current_generation,
        ):
            pass
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_external_message_clear_boundary_survives_restart(tmp_path: Path) -> None:
    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        StaleExternalUserMessageError,
    )

    db_path = tmp_path / "runtime_commands.db"
    first = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await first.start()
    async with first.user_message_clear_boundary():
        await first.advance_user_message_generation_and_purge()
    with sqlite3.connect(db_path) as conn:
        cleared_at_ms = int(
            float(
                conn.execute(
                    "SELECT updated_at FROM runtime_user_message_clear_state "
                    "WHERE singleton_id = 1"
                ).fetchone()[0]
            )
            * 1000
        )
    await first.stop()

    restarted = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await restarted.start()
    try:
        with pytest.raises(StaleExternalUserMessageError):
            await restarted.capture_external_user_message_context(
                provider_occurred_at_ms=cleared_at_ms,
            )
        assert (
            await restarted.capture_external_user_message_context(
                provider_occurred_at_ms=cleared_at_ms + 1,
            )
            == 1
        )
        assert await restarted.read_current_clear_generation() == 1
        assert (
            await restarted.capture_external_user_message_context(
                cursor_clear_generation=1,
            )
            == 1
        )
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_external_cursor_proof_must_exactly_match_durable_generation(
    tmp_path: Path,
) -> None:
    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        StaleExternalUserMessageError,
    )

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    try:
        assert (
            await queue.capture_external_user_message_context(
                cursor_clear_generation=0,
            )
            == 0
        )
        async with queue.user_message_global_clear_boundary():
            generation, _ = await queue.advance_user_message_generation_and_purge()
        assert generation == 1

        for stale_generation in (0, 2):
            with pytest.raises(StaleExternalUserMessageError):
                await queue.capture_external_user_message_context(
                    cursor_clear_generation=stale_generation,
                )

        captured_generation = await queue.capture_external_user_message_context(
            cursor_clear_generation=1,
        )
        async with queue.external_user_message_operation(
            cursor_clear_generation=1,
            captured_generation=captured_generation,
        ):
            pass

        async with queue.user_message_global_clear_boundary():
            await queue.advance_user_message_generation_and_purge()
        with pytest.raises(StaleExternalUserMessageError):
            async with queue.external_user_message_operation(
                cursor_clear_generation=1,
                captured_generation=captured_generation,
            ):
                pass
    finally:
        await queue.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_time", "cursor_generation"),
    [
        (None, None),
        (1, 0),
        (None, -1),
        (None, True),
        (None, 1.5),
        (None, "1"),
    ],
)
async def test_external_message_context_requires_one_valid_proof(
    tmp_path: Path,
    provider_time: object | None,
    cursor_generation: object | None,
) -> None:
    from magi.events.runtime_queue import (
        InvalidExternalUserMessageMetadataError,
        SQLiteRuntimeCommandQueue,
    )

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    try:
        with pytest.raises(InvalidExternalUserMessageMetadataError):
            await queue.capture_external_user_message_context(
                provider_occurred_at_ms=provider_time,
                cursor_clear_generation=cursor_generation,
            )
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_global_clear_waits_for_active_external_message_mutation(
    tmp_path: Path,
) -> None:
    import asyncio

    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    context_generation = await queue.capture_external_user_message_context(
        provider_occurred_at_ms=1,
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    cleared = asyncio.Event()

    async def mutate() -> None:
        async with queue.external_user_message_operation(
            provider_occurred_at_ms=1,
            captured_generation=context_generation,
        ):
            entered.set()
            await release.wait()

    async def clear() -> None:
        await entered.wait()
        async with queue.user_message_global_clear_boundary():
            await queue.advance_user_message_generation_and_purge()
            cleared.set()

    mutation_task = asyncio.create_task(mutate())
    clear_task = asyncio.create_task(clear())
    try:
        await entered.wait()
        await asyncio.sleep(0)
        assert not cleared.is_set()
        release.set()
        await asyncio.wait_for(asyncio.gather(mutation_task, clear_task), timeout=1)
        assert cleared.is_set()
    finally:
        release.set()
        await asyncio.gather(mutation_task, clear_task, return_exceptions=True)
        await queue.stop()


@pytest.mark.asyncio
async def test_global_clear_rejects_provider_events_that_occur_during_clear(
    tmp_path: Path,
) -> None:
    import asyncio

    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        StaleExternalUserMessageError,
    )

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    try:
        async with queue.user_message_global_clear_boundary():
            await queue.advance_user_message_generation_and_purge()
            with sqlite3.connect(queue.db_path) as conn:
                clear_started_at_ms = int(
                    float(
                        conn.execute(
                            "SELECT updated_at FROM runtime_user_message_clear_state "
                            "WHERE singleton_id = 1"
                        ).fetchone()[0]
                    )
                    * 1000
                )
            await asyncio.sleep(0.01)

        with sqlite3.connect(queue.db_path) as conn:
            clear_finished_at_ms = int(
                float(
                    conn.execute(
                        "SELECT updated_at FROM runtime_user_message_clear_state "
                        "WHERE singleton_id = 1"
                    ).fetchone()[0]
                )
                * 1000
            )
        assert clear_finished_at_ms > clear_started_at_ms

        with pytest.raises(StaleExternalUserMessageError):
            await queue.capture_external_user_message_context(
                provider_occurred_at_ms=clear_started_at_ms + 1,
            )
        assert (
            await queue.capture_external_user_message_context(
                provider_occurred_at_ms=clear_finished_at_ms + 1,
            )
            == 1
        )
    finally:
        await queue.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_value", [None, 0, -1, True, 1.5, "1"])
async def test_external_message_context_fails_closed_without_valid_provider_time(
    tmp_path: Path,
    invalid_value: object,
) -> None:
    from magi.events.runtime_queue import (
        InvalidExternalUserMessageMetadataError,
        SQLiteRuntimeCommandQueue,
    )

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    try:
        with pytest.raises(InvalidExternalUserMessageMetadataError):
            await queue.capture_external_user_message_context(
                provider_occurred_at_ms=invalid_value,  # type: ignore[arg-type]
            )
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_session_delete_barrier_purges_only_matching_payloads_and_survives_restart(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import (
        SQLiteRuntimeCommandQueue,
        UserMessageScopeBlockedError,
    )

    db_path = tmp_path / "runtime_commands.db"
    queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await queue.start()

    def _command(session_id: str, turn_id: str, message_id: str) -> UserMessageCommand:
        return UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id=session_id,
            turn_id=turn_id,
            message=f"private:{message_id}",
            correlation_id=f"user_message:{message_id}",
        )

    try:
        await queue.enqueue_user_message(_command("session-delete", "turn-1", "message-1"))
        completed = await queue.claim_next(
            consumer_name="worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert completed is not None
        await queue.ack(completed.command_id)
        await queue.enqueue_user_message(_command("session-delete", "turn-2", "message-2"))
        kept_id = await queue.enqueue_user_message(_command("session-keep", "turn-3", "message-3"))

        async with queue.user_message_clear_boundary():
            purged = await queue.block_user_message_scope_and_purge(
                user_id="user-1",
                session_id="session-delete",
                reason="user_delete_chat_session",
            )

        assert purged == 2
        assert await queue.is_user_message_scope_blocked(
            user_id="user-1",
            session_id="session-delete",
        )
        assert not await queue.is_user_message_scope_blocked(
            user_id="user-1",
            session_id="session-keep",
        )
        with pytest.raises(UserMessageScopeBlockedError):
            await queue.enqueue_user_message(_command("session-delete", "turn-new", "message-new"))

        kept = await queue.claim_next(
            consumer_name="worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert kept is not None
        assert kept.command_id == kept_id
    finally:
        await queue.stop()

    restarted = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await restarted.start()
    try:
        assert await restarted.is_user_message_scope_blocked(
            user_id="user-1",
            session_id="session-delete",
        )
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_message_delete_barrier_keeps_sibling_turns_in_same_session(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    async def _enqueue(turn_id: str, message_id: str) -> int:
        return await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id=turn_id,
                message=message_id,
                correlation_id=f"user_message:{message_id}",
            )
        )

    try:
        await _enqueue("turn-delete", "message-delete")
        kept_id = await _enqueue("turn-keep", "message-keep")

        async with queue.user_message_clear_boundary():
            purged = await queue.block_user_message_scope_and_purge(
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-delete",
                message_id="message-delete",
                reason="user_delete_chat_message",
            )

        assert purged == 1
        assert await queue.is_user_message_scope_blocked(
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-delete",
        )
        assert not await queue.is_user_message_scope_blocked(
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-keep",
        )
        kept = await queue.claim_next(
            consumer_name="worker",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert kept is not None
        assert kept.command_id == kept_id
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_user_message_can_reenqueue_same_correlation_after_destructive_clear(
    tmp_path: Path,
) -> None:
    from magi.core.sqlite import sqlite_connection_async
    from magi.events.contracts import UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    command = UserMessageCommand(
        source="api",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        message="same business input",
        correlation_id="user_message:message-1",
        created_at=1710000000.0,
    )
    try:
        first_command_id = await queue.enqueue_user_message(command)
        async with queue.user_message_clear_boundary():
            generation, purged = await queue.advance_user_message_generation_and_purge()

        assert generation == 1
        assert purged == 1
        async with sqlite_connection_async(queue.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(*)
                FROM runtime_user_message_idempotency
                WHERE correlation_id = ?
                """,
                (command.correlation_id,),
            ) as cursor:
                assert int((await cursor.fetchone())[0]) == 0

        second_command_id = await queue.enqueue_user_message(command)
        assert second_command_id != first_command_id
        async with sqlite_connection_async(queue.db_path) as db:
            async with db.execute(
                """
                SELECT user_message_generation
                FROM runtime_commands
                WHERE command_id = ?
                """,
                (second_command_id,),
            ) as cursor:
                assert int((await cursor.fetchone())[0]) == 1
    finally:
        await queue.stop()

    reloaded = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await reloaded.start()
    try:
        assert reloaded.current_user_message_generation() == 1
    finally:
        await reloaded.stop()


@pytest.mark.asyncio
async def test_first_clear_purges_legacy_user_message_migrated_from_v1(
    tmp_path: Path,
) -> None:
    import json
    import sqlite3
    import time

    from alembic import command

    from magi.db.runner import MIGRATION_TARGETS, _build_config
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    db_path = tmp_path / "legacy_message_queue.db"
    target = next(target for target in MIGRATION_TARGETS if target.name == "message_queue")
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")
    now = time.time()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status, retry_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                "user_message",
                json.dumps({"message": "legacy private text"}),
                "legacy-command",
                "completed",
                now,
                now,
            ),
        )
        conn.commit()
    command.upgrade(config, "head")

    queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await queue.start()
    try:
        assert queue.current_user_message_generation() == 0
        async with queue.user_message_clear_boundary():
            generation, purged = await queue.advance_user_message_generation_and_purge()
        assert generation == 1
        assert purged == 1
        with sqlite3.connect(db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM runtime_commands WHERE command_type = 'user_message'"
            ).fetchone() == (0,)
    finally:
        await queue.stop()
