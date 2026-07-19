"""Chat-owned runtime barriers for user-requested transcript deletion."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatRuntimeForgetResult:
    """Counts produced while removing pending runtime work."""

    purged_commands: int = 0
    purged_sensor_events: int = 0
    cancelled_agent: bool = False


class _MessageDeleteHoldProtocol(Protocol):
    """Held runtime state required by one exact message deletion."""

    cancelled_agent: bool
    cancellation_error: BaseException | None
    terminal_turn_ids: tuple[str, ...]
    replay_turn_ids: tuple[str, ...]

    async def prepare_after_barrier(self) -> None: ...


class _TaskAgentManagerProtocol(Protocol):
    """Task-agent controls used by chat forgetting."""

    def hold_chat_session_for_message_delete(
        self,
        *,
        session_id: str,
        turn_id: str,
        expected_run_id: str | None,
        expected_run_revision: int,
        match_turn_scope: bool,
    ) -> Any: ...

    async def cancel_chat_session_work(
        self,
        *,
        session_id: str,
        turn_id: str | None = None,
        expected_run_id: str | None = None,
        expected_run_revision: int | None = None,
        require_run_match: bool = False,
        match_turn_scope: bool = False,
    ) -> bool: ...


class _L0ExecutionStoreProtocol(Protocol):
    """L0 deletion operation required by context replay."""

    async def forget_execution_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> None: ...


class _BackgroundTaskManagerProtocol(Protocol):
    def conversation_scope_boundary(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        origin_turn_ids: set[str] | None = None,
        task_ids: set[str] | None = None,
        pending_message_ids: set[str] | None = None,
        reason: str = "conversation_deleted",
        timeout_seconds: float = 30.0,
    ) -> Any: ...

    async def cancel_scope_and_wait(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        origin_turn_ids: set[str] | None = None,
        task_ids: set[str] | None = None,
        pending_message_ids: set[str] | None = None,
        reason: str = "conversation_deleted",
        timeout_seconds: float = 30.0,
    ) -> int: ...


class ChatRuntimeForgettingCoordinator:
    """Block deleted chat work before memory and transcript cleanup."""

    def __init__(
        self,
        *,
        runtime_command_queue: Any,
        task_agent_manager: _TaskAgentManagerProtocol | None,
        sensor_hub: Any | None,
        chat_read_service: Any,
        delivery_scheduler: Any,
        l0_store: _L0ExecutionStoreProtocol | None = None,
        background_task_manager: _BackgroundTaskManagerProtocol | None = None,
    ) -> None:
        self._runtime_command_queue = runtime_command_queue
        self._task_agent_manager = task_agent_manager
        self._sensor_hub = sensor_hub
        self._chat_read_service = chat_read_service
        self._delivery_scheduler = delivery_scheduler
        self._l0_store = l0_store
        self._background_task_manager = background_task_manager

    @asynccontextmanager
    async def forget_operation_boundary(self) -> AsyncIterator[None]:
        """Serialize chat deletion with full-memory clearing."""

        async with self._runtime_command_queue.user_message_destructive_operation():
            yield

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
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str] | None = None,
        replay_turn_ids: list[str] | None = None,
        related_message_ids: list[str] | None = None,
        background_task_ids: list[str] | None = None,
    ) -> ChatRuntimeForgetResult:
        """Prepare and immediately release a standalone message deletion."""

        async with self.message_delete_boundary(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            include_turn_scope=include_turn_scope,
            run_id=run_id,
            run_revision=run_revision,
            runtime_turn_ids=runtime_turn_ids or [turn_id],
            replay_turn_ids=replay_turn_ids,
            related_message_ids=related_message_ids,
            background_task_ids=background_task_ids,
        ) as result:
            return result

    @asynccontextmanager
    async def message_delete_boundary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str] | None = None,
        replay_turn_ids: list[str] | None = None,
        related_message_ids: list[str] | None = None,
        background_task_ids: list[str] | None = None,
        prepare_intent: (
            Callable[[list[str], list[str]], Awaitable[None]] | None
        ) = None,
    ) -> AsyncIterator[ChatRuntimeForgetResult]:
        """Hold one session until memory and chat surfaces finish deletion."""

        hold_context = self._message_delete_hold(
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            run_revision=run_revision,
            match_turn_scope=include_turn_scope,
        )
        async with hold_context as hold, AsyncExitStack() as stack:
            queue = self._runtime_command_queue
            terminal_turn_ids = _normalized_turn_ids(
                [
                    *list(runtime_turn_ids or ()),
                    *hold.terminal_turn_ids,
                    turn_id,
                ]
            )
            hold.terminal_turn_ids = tuple(terminal_turn_ids)
            replay_turn_ids = [
                value
                for value in _normalized_turn_ids(
                    [
                        *list(replay_turn_ids or ()),
                        *hold.replay_turn_ids,
                    ]
                )
                if value not in terminal_turn_ids
            ]
            hold.replay_turn_ids = tuple(replay_turn_ids)
            message_scope_ids = _normalized_identifiers(
                [
                    message_id,
                    *list(related_message_ids or ()),
                ]
            )
            await stack.enter_async_context(
                self.background_scope_boundary(
                    user_id=user_id,
                    session_id=session_id,
                    turn_ids=[
                        *terminal_turn_ids,
                        *replay_turn_ids,
                    ],
                    task_ids=background_task_ids,
                    pending_message_ids=message_scope_ids,
                    reason="user_delete_chat_message",
                )
            )
            if prepare_intent is not None:
                await prepare_intent(terminal_turn_ids, replay_turn_ids)

            blocked_turn_ids: set[str] = set()
            async with queue.user_message_clear_boundary():
                purged_commands = 0
                for scoped_message_id in message_scope_ids:
                    purged_commands += (
                        await queue.block_user_message_scope_and_purge(
                            user_id=user_id,
                            session_id=session_id,
                            turn_id=None,
                            message_id=scoped_message_id,
                            reason="user_delete_chat_message",
                        )
                    )
                for runtime_turn_id in (
                    *terminal_turn_ids,
                    *replay_turn_ids,
                ):
                    purged_commands += (
                        await queue.block_user_message_scope_and_purge(
                            user_id=user_id,
                            session_id=session_id,
                            turn_id=runtime_turn_id,
                            message_id=None,
                            reason="user_delete_chat_message",
                        )
                    )
                    blocked_turn_ids.add(runtime_turn_id)

            await hold.prepare_after_barrier()

            terminal_turn_ids = _normalized_turn_ids(
                [
                    *terminal_turn_ids,
                    *hold.terminal_turn_ids,
                ]
            )
            hold.terminal_turn_ids = tuple(terminal_turn_ids)
            late_terminal_turn_ids = [
                value
                for value in terminal_turn_ids
                if value not in blocked_turn_ids
            ]
            if late_terminal_turn_ids:
                raise RuntimeError(
                    "Message deletion discovered an unprepared runtime turn"
                )

            if (
                hold.cancellation_error is not None
                and not hold.cancelled_agent
            ):
                raise RuntimeError(
                    "Failed to cancel chat run before message deletion"
                ) from hold.cancellation_error

            await self._forget_runtime_execution_turns(
                session_id=session_id,
                turn_ids=[
                    *replay_turn_ids,
                    *(terminal_turn_ids if include_turn_scope else []),
                ],
            )
            survivors = []
            if terminal_turn_ids:
                survivors = (
                    await self._chat_read_service.abump_nonterminal_user_turn_delivery_attempts(
                        user_id,
                        session_id,
                        terminal_turn_ids,
                        int(time.time() * 1000),
                        bump_survivors=(
                            hold.cancelled_agent or bool(replay_turn_ids)
                        ),
                    )
                )
            if hold.cancellation_error is not None:
                raise RuntimeError(
                    "Failed to cancel chat run before message deletion"
                ) from hold.cancellation_error

            purged_sensor_events = 0
            if self._sensor_hub is not None:
                for scoped_message_id in message_scope_ids:
                    purged_sensor_events += int(
                        await self._sensor_hub.discard_user_message_scope(
                            user_id=user_id,
                            session_id=session_id,
                            turn_id=None,
                            message_id=scoped_message_id,
                        )
                    )
                for runtime_turn_id in (
                    *terminal_turn_ids,
                    *replay_turn_ids,
                ):
                    purged_sensor_events += int(
                        await self._sensor_hub.discard_user_message_scope(
                            user_id=user_id,
                            session_id=session_id,
                            turn_id=runtime_turn_id,
                            message_id=None,
                        )
                    )
            yield ChatRuntimeForgetResult(
                purged_commands=purged_commands,
                purged_sensor_events=purged_sensor_events,
                cancelled_agent=hold.cancelled_agent,
            )
            if survivors:
                try:
                    failures = await self._delivery_scheduler.schedule_records(
                        survivors
                    )
                except Exception:
                    logger.exception(
                        "Failed to schedule surviving user turns after message deletion",
                        session_id=session_id,
                    )
                else:
                    if failures:
                        logger.warning(
                            "Some surviving user turns remain ready after message deletion",
                            session_id=session_id,
                            failed_count=len(failures),
                        )

    async def _forget_runtime_execution_turns(
        self,
        *,
        session_id: str,
        turn_ids: list[str],
    ) -> None:
        """Remove exact unsafe L0 execution state before context replay."""

        if self._l0_store is None:
            return
        for turn_id in _normalized_turn_ids(turn_ids):
            await self._l0_store.forget_execution_turn(
                session_id=session_id,
                turn_id=turn_id,
            )

    @asynccontextmanager
    async def _message_delete_hold(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str | None,
        run_revision: int,
        match_turn_scope: bool,
    ) -> AsyncIterator[_MessageDeleteHoldProtocol]:
        manager = self._task_agent_manager
        if manager is None:
            yield _EmptyMessageDeleteHold()
            return
        async with manager.hold_chat_session_for_message_delete(
            session_id=session_id,
            turn_id=turn_id,
            expected_run_id=run_id,
            expected_run_revision=run_revision,
            match_turn_scope=match_turn_scope,
        ) as hold:
            yield hold

    async def prepare_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        message_ids: list[str],
    ) -> ChatRuntimeForgetResult:
        """Block the exact old transcript snapshot without blocking the session."""
        normalized_turn_ids = sorted(
            {str(turn_id or "").strip() for turn_id in turn_ids if str(turn_id or "").strip()}
        )
        normalized_message_ids = {
            normalized
            for value in message_ids
            if (normalized := str(value or "").strip())
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
            for message_id in sorted(normalized_message_ids):
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
            for message_id in sorted(normalized_message_ids):
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
        await self._cancel_background_scope(
            user_id=user_id,
            session_id=session_id,
            turn_ids=None,
            reason="user_clear_chat_history",
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
        cancellation_turn_id: str | None = None,
        cancellation_run_id: str | None = None,
        cancellation_run_revision: int | None = None,
        require_cancellation_run_match: bool = False,
        cancellation_match_turn_scope: bool = False,
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
                    turn_id=(
                        cancellation_turn_id
                        if cancellation_turn_id is not None
                        else turn_id
                    ),
                    expected_run_id=cancellation_run_id,
                    expected_run_revision=cancellation_run_revision,
                    require_run_match=require_cancellation_run_match,
                    match_turn_scope=cancellation_match_turn_scope,
                )
                )

        await self._cancel_background_scope(
            user_id=user_id,
            session_id=session_id,
            turn_ids=[turn_id] if turn_id else None,
            reason=reason,
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

    async def _cancel_background_scope(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str] | None,
        task_ids: list[str] | None = None,
        pending_message_ids: list[str] | None = None,
        reason: str,
    ) -> int:
        manager = self._background_task_manager
        if manager is None:
            return 0
        normalized_turn_ids = (
            set(_normalized_turn_ids(turn_ids))
            if turn_ids is not None
            else None
        )
        normalized_task_ids = (
            set(_normalized_identifiers(task_ids))
            if task_ids is not None
            else None
        )
        normalized_pending_message_ids = (
            set(_normalized_identifiers(pending_message_ids))
            if pending_message_ids is not None
            else None
        )
        scope: dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "origin_turn_ids": normalized_turn_ids,
            "reason": reason,
        }
        if normalized_task_ids:
            scope["task_ids"] = normalized_task_ids
        if normalized_pending_message_ids:
            scope["pending_message_ids"] = normalized_pending_message_ids
        return await manager.cancel_scope_and_wait(
            **scope,
        )

    @asynccontextmanager
    async def background_scope_boundary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str] | None,
        task_ids: list[str] | None = None,
        pending_message_ids: list[str] | None = None,
        reason: str,
    ) -> AsyncIterator[None]:
        """Reject matching background admission until deletion is finished."""

        manager = self._background_task_manager
        if manager is None:
            yield
            return
        normalized_turn_ids = (
            set(_normalized_turn_ids(turn_ids))
            if turn_ids is not None
            else None
        )
        normalized_task_ids = (
            set(_normalized_identifiers(task_ids))
            if task_ids is not None
            else None
        )
        normalized_pending_message_ids = (
            set(_normalized_identifiers(pending_message_ids))
            if pending_message_ids is not None
            else None
        )
        scope: dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "origin_turn_ids": normalized_turn_ids,
            "reason": reason,
        }
        if normalized_task_ids:
            scope["task_ids"] = normalized_task_ids
        if normalized_pending_message_ids:
            scope["pending_message_ids"] = normalized_pending_message_ids
        async with manager.conversation_scope_boundary(**scope):
            yield


@dataclass(slots=True)
class _EmptyMessageDeleteHold:
    cancelled_agent: bool = False
    cancellation_error: BaseException | None = None
    terminal_turn_ids: tuple[str, ...] = ()
    replay_turn_ids: tuple[str, ...] = ()

    async def prepare_after_barrier(self) -> None:
        """No-op when no task-agent runtime is available."""


def _normalized_turn_ids(values: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            normalized
            for value in values
            if (normalized := str(value or "").strip())
        )
    )


def _normalized_identifiers(values: list[str] | None) -> list[str]:
    return list(
        dict.fromkeys(
            normalized
            for value in values or ()
            if (normalized := str(value or "").strip())
        )
    )


__all__ = ["ChatRuntimeForgetResult", "ChatRuntimeForgettingCoordinator"]
