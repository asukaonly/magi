"""Session-local task-agent coordination for exact chat-message deletion."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from ...core.logger import get_logger
from .task_agent import TaskAgent
from .types import TaskAgentType, build_task_agent_key

logger = get_logger(__name__)


@dataclass(slots=True)
class ChatMessageDeleteHold:
    """One session-local deletion hold."""

    cancelled_agent: bool = False
    cancellation_error: BaseException | None = None
    terminal_turn_ids: tuple[str, ...] = ()
    replay_turn_ids: tuple[str, ...] = ()
    _prepare_after_barrier: Callable[[], Awaitable[None]] | None = field(
        default=None,
        repr=False,
    )
    _prepared: bool = field(default=False, repr=False)

    async def prepare_after_barrier(self) -> None:
        """Quiesce only after the deleted delivery can no longer re-enter."""

        if self._prepared:
            return
        self._prepared = True
        if self._prepare_after_barrier is not None:
            await self._prepare_after_barrier()


class ChatSessionControlAgent(Protocol):
    """Chat-agent control contract required by destructive session mutations."""

    async def plan_message_delete_runtime_turn_ids(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]: ...

    async def discard_pending_turn_for_message_delete(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str | None,
        run_revision: int | None,
    ) -> bool: ...

    def matches_active_session_run(
        self,
        *,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        run_revision: int | None,
        match_turn_scope: bool,
    ) -> bool: ...

    def active_root_turn_id_for_message_delete(
        self,
        *,
        session_id: str,
    ) -> str | None: ...

    async def abandon_session_run_for_context_replay(
        self,
        *,
        session_id: str,
        replay_turn_ids: tuple[str, ...],
    ) -> bool: ...


class ChatMessageDeleteCoordinator:
    """Own the session hold and chat-agent cleanup for transcript deletion."""

    def __init__(
        self,
        *,
        chat_clear_lock: asyncio.Lock,
        agents: MutableMapping[str, TaskAgent],
        instance_metadata: MutableMapping[str, Any],
        session_quiesce_events: MutableMapping[str, asyncio.Event],
        cancel_and_stop: Callable[..., Awaitable[None]],
    ) -> None:
        self._chat_clear_lock = chat_clear_lock
        self._agents = agents
        self._instance_metadata = instance_metadata
        self._session_quiesce_events = session_quiesce_events
        self._cancel_and_stop = cancel_and_stop

    async def cancel_session_work(
        self,
        *,
        session_id: str,
        turn_id: str | None = None,
        expected_run_id: str | None = None,
        expected_run_revision: int | None = None,
        require_run_match: bool = False,
        match_turn_scope: bool = False,
    ) -> bool:
        """Stop any session run that may have consumed a deleted user turn."""

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_session_id:
            raise ValueError("Session ID is required")
        key = build_task_agent_key(TaskAgentType.CHAT, normalized_session_id)
        while True:
            wait_for_quiesce: asyncio.Event | None = None
            async with self._chat_clear_lock:
                wait_for_quiesce = self._session_quiesce_events.get(
                    normalized_session_id
                )
                if wait_for_quiesce is None:
                    agent = self._agents.get(key)
                    if require_run_match and agent is not None:
                        chat_agent = cast(ChatSessionControlAgent, agent)
                        if not chat_agent.matches_active_session_run(
                            session_id=normalized_session_id,
                            turn_id=normalized_turn_id or None,
                            run_id=expected_run_id,
                            run_revision=expected_run_revision,
                            match_turn_scope=match_turn_scope,
                        ):
                            return False
                    if agent is None:
                        return False
                    metadata = self._instance_metadata.pop(key, None)
                    self._agents.pop(key, None)
                    quiesce_event = asyncio.Event()
                    self._session_quiesce_events[normalized_session_id] = (
                        quiesce_event
                    )
                    break
            await wait_for_quiesce.wait()

        try:
            cancel_error: BaseException | None = None
            try:
                await self._cancel_and_stop(
                    agent,
                    reason="privacy_delete",
                    anchor_turn_id=normalized_turn_id or None,
                )
            except BaseException as exc:
                cancel_error = exc

            if cancel_error is not None and not self._agent_is_stopped(agent):
                async with self._chat_clear_lock:
                    self._agents[key] = agent
                    if metadata is not None:
                        self._instance_metadata[key] = metadata
                raise cancel_error

            if cancel_error is not None:
                raise cancel_error
            return True
        finally:
            async with self._chat_clear_lock:
                self._release_session_quiesce(
                    session_id=normalized_session_id,
                    event=quiesce_event,
                )

    @asynccontextmanager
    async def hold_session_for_message_delete(
        self,
        *,
        session_id: str,
        turn_id: str,
        expected_run_id: str | None,
        expected_run_revision: int,
        match_turn_scope: bool,
    ) -> AsyncIterator[ChatMessageDeleteHold]:
        """Hold one session while an exact message deletion is finalized."""

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_session_id:
            raise ValueError("Session ID is required")
        key = build_task_agent_key(TaskAgentType.CHAT, normalized_session_id)
        while True:
            wait_for_quiesce: asyncio.Event | None = None
            async with self._chat_clear_lock:
                wait_for_quiesce = self._session_quiesce_events.get(
                    normalized_session_id
                )
                if wait_for_quiesce is None:
                    agent = self._agents.get(key)
                    quiesce_event = asyncio.Event()
                    self._session_quiesce_events[normalized_session_id] = (
                        quiesce_event
                    )
                    break
            await wait_for_quiesce.wait()

        try:
            terminal_turn_ids = (
                (normalized_turn_id,) if normalized_turn_id else ()
            )
            replay_turn_ids: tuple[str, ...] = ()
            chat_agent = (
                cast(ChatSessionControlAgent, agent)
                if agent is not None
                else None
            )
            if chat_agent is not None:
                terminal_turn_ids, replay_turn_ids = (
                    await chat_agent.plan_message_delete_runtime_turn_ids(
                        session_id=normalized_session_id,
                        turn_id=normalized_turn_id,
                    )
                )
                terminal_turn_ids = tuple(terminal_turn_ids)
                replay_turn_ids = tuple(
                    value
                    for value in replay_turn_ids
                    if value not in terminal_turn_ids
                )

            hold = ChatMessageDeleteHold(
                terminal_turn_ids=terminal_turn_ids,
                replay_turn_ids=replay_turn_ids,
            )

            async def _prepare_after_barrier() -> None:
                if agent is None or chat_agent is None:
                    return
                if match_turn_scope:
                    try:
                        if await chat_agent.discard_pending_turn_for_message_delete(
                            session_id=normalized_session_id,
                            turn_id=normalized_turn_id,
                            run_id=expected_run_id,
                            run_revision=expected_run_revision,
                        ):
                            return
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        hold.cancellation_error = exc
                        logger.exception(
                            "Failed to discard pending chat turn during message deletion",
                            session_id=normalized_session_id,
                            turn_id=normalized_turn_id,
                        )
                        return

                metadata: Any | None = None
                replay_agent = False
                async with self._chat_clear_lock:
                    current_agent = self._agents.get(key)
                    if current_agent is not agent:
                        return
                    matches_agent = chat_agent.matches_active_session_run(
                        session_id=normalized_session_id,
                        turn_id=normalized_turn_id or None,
                        run_id=expected_run_id,
                        run_revision=expected_run_revision,
                        match_turn_scope=match_turn_scope,
                    )
                    cancel_reason = "privacy_delete"
                    cancel_anchor_turn_id = normalized_turn_id or None
                    if not matches_agent:
                        active_root_turn_id = (
                            chat_agent.active_root_turn_id_for_message_delete(
                                session_id=normalized_session_id
                            )
                        )
                        if (
                            active_root_turn_id
                            and active_root_turn_id in hold.replay_turn_ids
                        ):
                            replay_agent = True
                            cancel_anchor_turn_id = active_root_turn_id
                        elif not active_root_turn_id and hold.replay_turn_ids:
                            replay_agent = True
                            cancel_anchor_turn_id = hold.replay_turn_ids[0]
                        elif not active_root_turn_id:
                            return
                        else:
                            cancel_reason = "privacy_context_changed"
                            cancel_anchor_turn_id = active_root_turn_id
                    if not replay_agent:
                        hold.terminal_turn_ids = tuple(
                            dict.fromkeys(
                                value
                                for value in (
                                    *hold.terminal_turn_ids,
                                    str(cancel_anchor_turn_id or "").strip(),
                                )
                                if value
                            )
                        )
                    metadata = self._instance_metadata.pop(key, None)
                    self._agents.pop(key, None)

                cancel_error: BaseException | None = None
                try:
                    if replay_agent:
                        await self._stop_for_context_replay(
                            agent,
                            session_id=normalized_session_id,
                            replay_turn_ids=hold.replay_turn_ids,
                        )
                    else:
                        await self._cancel_and_stop(
                            agent,
                            reason=cancel_reason,
                            anchor_turn_id=cancel_anchor_turn_id,
                        )
                except BaseException as exc:
                    cancel_error = exc

                stopped = self._agent_is_stopped(agent)
                if cancel_error is not None and not stopped:
                    async with self._chat_clear_lock:
                        if key not in self._agents:
                            self._agents[key] = agent
                            if metadata is not None:
                                self._instance_metadata[key] = metadata
                hold.cancelled_agent = stopped
                hold.cancellation_error = cancel_error

            hold._prepare_after_barrier = _prepare_after_barrier
            yield hold
        finally:
            async with self._chat_clear_lock:
                self._release_session_quiesce(
                    session_id=normalized_session_id,
                    event=quiesce_event,
                )

    @staticmethod
    async def _stop_for_context_replay(
        agent: TaskAgent,
        *,
        session_id: str,
        replay_turn_ids: tuple[str, ...],
    ) -> None:
        """Stop unsafe work and clear its run without terminalizing delivery."""

        await agent.stop()
        chat_agent = cast(ChatSessionControlAgent, agent)
        await chat_agent.abandon_session_run_for_context_replay(
            session_id=session_id,
            replay_turn_ids=replay_turn_ids,
        )

    def _release_session_quiesce(
        self,
        *,
        session_id: str,
        event: asyncio.Event,
    ) -> None:
        if self._session_quiesce_events.get(session_id) is event:
            self._session_quiesce_events.pop(session_id, None)
        event.set()

    @staticmethod
    def _agent_is_stopped(agent: TaskAgent) -> bool:
        task = agent._task
        return not agent._running and (
            task is None or bool(task.done())
        )


__all__ = [
    "ChatMessageDeleteCoordinator",
    "ChatMessageDeleteHold",
    "ChatSessionControlAgent",
]
