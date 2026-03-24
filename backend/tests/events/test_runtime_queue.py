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
