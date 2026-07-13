from __future__ import annotations

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
