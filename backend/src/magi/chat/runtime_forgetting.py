"""Chat-owned runtime barriers for user-requested transcript deletion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .read.models import ChatMessageSourceIdentity


@dataclass(frozen=True, slots=True)
class ChatRuntimeForgetResult:
    """Counts produced while removing pending runtime work."""

    purged_commands: int = 0
    purged_sensor_events: int = 0
    cancelled_agent: bool = False


class ChatRuntimeForgettingCoordinator:
    """Block deleted chat work before memory and transcript cleanup."""

    def __init__(
        self,
        *,
        runtime_command_queue: Any,
        task_agent_manager: Any | None,
        sensor_hub: Any | None,
    ) -> None:
        self._runtime_command_queue = runtime_command_queue
        self._task_agent_manager = task_agent_manager
        self._sensor_hub = sensor_hub

    async def prepare_session_delete(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> ChatRuntimeForgetResult:
        """Permanently reject and drain all runtime work for one session."""
        return await self._prepare(
            user_id=user_id,
            session_id=session_id,
            turn_id=None,
            message_id=None,
            reason="user_delete_chat_session",
        )

    async def prepare_message_delete(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
    ) -> ChatRuntimeForgetResult:
        """Permanently reject and drain one exact user-message turn."""
        return await self._prepare(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            reason="user_delete_chat_message",
        )

    async def prepare_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        messages: list[ChatMessageSourceIdentity],
    ) -> ChatRuntimeForgetResult:
        """Block the exact old transcript snapshot without blocking the session."""
        normalized_turn_ids = sorted(
            {str(turn_id or "").strip() for turn_id in turn_ids if str(turn_id or "").strip()}
        )
        message_by_id = {
            str(message.message_id): message
            for message in messages
            if str(message.message_id or "").strip()
        }
        purged_commands = 0
        async with self._runtime_command_queue.user_message_clear_boundary():
            for turn_id in normalized_turn_ids:
                purged_commands += (
                    await self._runtime_command_queue.block_user_message_scope_and_purge(
                        user_id=user_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        message_id=None,
                        reason="user_clear_chat_history",
                    )
                )
            for message_id in sorted(message_by_id):
                purged_commands += (
                    await self._runtime_command_queue.block_user_message_scope_and_purge(
                        user_id=user_id,
                        session_id=session_id,
                        turn_id=None,
                        message_id=message_id,
                        reason="user_clear_chat_history",
                    )
                )

        cancelled_agent = False
        if self._task_agent_manager is not None:
            for turn_id in normalized_turn_ids:
                cancelled_agent = (
                    bool(
                        await self._task_agent_manager.cancel_chat_session_work(
                            session_id=session_id,
                            turn_id=turn_id,
                        )
                    )
                    or cancelled_agent
                )

        purged_sensor_events = 0
        if self._sensor_hub is not None:
            for turn_id in normalized_turn_ids:
                purged_sensor_events += int(
                    await self._sensor_hub.discard_user_message_scope(
                        user_id=user_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        message_id=None,
                    )
                )
            for message_id in sorted(message_by_id):
                purged_sensor_events += int(
                    await self._sensor_hub.discard_user_message_scope(
                        user_id=user_id,
                        session_id=session_id,
                        turn_id=None,
                        message_id=message_id,
                    )
                )
        return ChatRuntimeForgetResult(
            purged_commands=purged_commands,
            purged_sensor_events=purged_sensor_events,
            cancelled_agent=cancelled_agent,
        )

    async def quiesce_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> ChatRuntimeForgetResult:
        """Wait for active session work to stop before the final source snapshot."""
        _ = user_id
        cancelled_agent = False
        if self._task_agent_manager is not None:
            cancelled_agent = bool(
                await self._task_agent_manager.cancel_chat_session_work(
                    session_id=session_id,
                    turn_id=None,
                )
            )
        return ChatRuntimeForgetResult(cancelled_agent=cancelled_agent)

    async def _prepare(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        message_id: str | None,
        reason: str,
    ) -> ChatRuntimeForgetResult:
        queue = self._runtime_command_queue
        async with queue.user_message_clear_boundary():
            purged_commands = await queue.block_user_message_scope_and_purge(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                message_id=message_id,
                reason=reason,
            )

        cancelled_agent = False
        if self._task_agent_manager is not None:
            cancelled_agent = bool(
                await self._task_agent_manager.cancel_chat_session_work(
                    session_id=session_id,
                    turn_id=turn_id,
                )
            )

        purged_sensor_events = 0
        if self._sensor_hub is not None:
            purged_sensor_events = int(
                await self._sensor_hub.discard_user_message_scope(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    message_id=message_id,
                )
            )

        return ChatRuntimeForgetResult(
            purged_commands=purged_commands,
            purged_sensor_events=purged_sensor_events,
            cancelled_agent=cancelled_agent,
        )


__all__ = ["ChatRuntimeForgetResult", "ChatRuntimeForgettingCoordinator"]
