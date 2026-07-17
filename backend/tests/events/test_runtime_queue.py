from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


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
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

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

        assert await queue.enqueue_user_message(original) == first_id
        assert (await queue.get_stats())["pending_count"] == 0

        second_id = await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="hello again",
                correlation_id="user_message:message-2",
                created_at=1710000001.0,
            )
        )
        assert second_id != first_id
        assert (await queue.get_stats())["pending_count"] == 1
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
async def test_runtime_command_queue_enqueues_and_claims_sensor_sync(tmp_path: Path) -> None:
    from magi.events.contracts import RuntimeCommandType, SensorSyncCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    try:
        queued_command_id = await queue.enqueue_sensor_sync(
            SensorSyncCommand(
                source="api",
                source_name="calendar",
            )
        )

        claimed = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.SENSOR_SYNC,),
        )

        assert claimed is not None
        assert claimed.command_id == queued_command_id
        assert claimed.command_type is RuntimeCommandType.SENSOR_SYNC
        assert claimed.payload["source_name"] == "calendar"
        assert claimed.payload["first_context"] is False

        await queue.ack(claimed.command_id)

        stats = await queue.get_stats()
        assert stats["pending_count"] == 0
        assert stats["claimed_count"] == 0
        assert stats["completed_count"] == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_queue_enqueues_and_claims_sensor_state_flush(tmp_path: Path) -> None:
    from magi.events.contracts import RuntimeCommandType, SensorStateFlushCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()

    try:
        queued_command_id = await queue.enqueue_sensor_state_flush(
            SensorStateFlushCommand(
                source="api",
                source_name="screen_time",
            )
        )

        claimed = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.SENSOR_STATE_FLUSH,),
        )

        assert claimed is not None
        assert claimed.command_id == queued_command_id
        assert claimed.command_type is RuntimeCommandType.SENSOR_STATE_FLUSH
        assert claimed.payload["source_name"] == "screen_time"

        await queue.ack(claimed.command_id)

        stats = await queue.get_stats()
        assert stats["pending_count"] == 0
        assert stats["claimed_count"] == 0
        assert stats["completed_count"] == 1
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

        async with queue.user_message_clear_boundary():
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
        assert [(row[0], "keep me" in str(row[1])) for row in rows] == [
            (RuntimeCommandType.REFRESH_LLM_CONFIG.value, True)
        ]
        assert all("secret" not in str(row[1]) for row in rows)
        assert receipt_count == 0

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
