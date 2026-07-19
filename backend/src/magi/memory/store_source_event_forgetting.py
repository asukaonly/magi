"""Public orchestration for durable cross-layer memory forgetting."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from ..core.sqlite import sqlite_connection_async
from .forgetting import (
    DurableForgetRunner,
    ForgetOperation,
    ForgetOutcome,
    ForgetSelector,
    SourceForgetBatch,
    SourceForgetClaim,
    SourceForgetGateResult,
    SourceForgetOwner,
    SourceForgetOwnerRegistry,
    SourceForgetOwnerUnavailableError,
)
from .source_event_governance import (
    normalize_source_event_ids,
    source_event_tombstone_ids,
)


class UnifiedSourceEventForgettingMixin:
    """Expose stable forget entry points backed by one resumable state machine."""

    memory_db_path: str
    l1: Any
    l2: Any
    _clear_barrier: Any
    _durable_forget_runner: DurableForgetRunner
    _source_forget_owners: SourceForgetOwnerRegistry

    @asynccontextmanager
    async def chat_forget_operation_guard(self) -> AsyncIterator[None]:
        """Keep one chat delete intent intact until its surface is finalized."""

        async with self._clear_barrier.operation():
            yield

    def register_source_forget_owner(
        self,
        name: str,
        owner: SourceForgetOwner,
    ) -> None:
        """Register one source-domain finalizer for exact forget batches."""
        registry = getattr(self, "_source_forget_owners", None)
        if registry is None:
            registry = SourceForgetOwnerRegistry()
            self._source_forget_owners = registry
        registry.register(name, owner)

    def unregister_source_forget_owner(self, name: str) -> None:
        """Remove a previously registered source-domain finalizer."""
        self._source_forget_owners.unregister(name)

    async def _notify_source_forget_owners(
        self,
        batch: SourceForgetBatch,
    ) -> SourceForgetGateResult:
        """Gate selected source-owned state before its page is checkpointed."""
        registry = getattr(self, "_source_forget_owners", None)
        if registry is None:
            return SourceForgetGateResult()
        return await registry.gate(batch)

    async def _finalize_source_forget_owners(
        self,
        claims: tuple[SourceForgetClaim, ...],
    ) -> None:
        """Finalize durable source obligations after memory cleanup."""
        registry = getattr(self, "_source_forget_owners", None)
        if registry is None:
            if claims:
                raise SourceForgetOwnerUnavailableError(
                    "Claimed source-forget owner registry is unavailable"
                )
            return
        await registry.finalize(claims)

    async def forget_chat_session_sources(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: Iterable[str] = (),
        reason: str = "user_delete_chat_session",
    ) -> ForgetOutcome:
        selector = ForgetSelector.chat_session(
            user_id=user_id,
            session_id=session_id,
            turn_ids=list(turn_ids),
        )
        outcome = await self._execute_durable_forget(
            selector,
            reason=reason,
            reuse_completed=True,
        )
        return outcome

    async def prepare_chat_session_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: Iterable[str] = (),
        reason: str = "user_delete_chat_session",
    ) -> ForgetOperation:
        """Persist a session-delete intent before blocking runtime delivery."""

        return await self._prepare_durable_forget(
            ForgetSelector.chat_session(
                user_id=user_id,
                session_id=session_id,
                turn_ids=list(turn_ids),
            ),
            reason=reason,
            reuse_completed=True,
            execution_ready=False,
        )

    async def forget_chat_message_source(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        turn_id: str,
        source: str,
        event_type: str,
        reason: str = "user_delete_chat_message",
    ) -> ForgetOutcome:
        selector = ForgetSelector.chat_message(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            source_message_id=message_id,
            turn_id=turn_id,
            source=source,
            event_type=event_type,
        )
        outcome = await self._execute_durable_forget(
            selector,
            reason=reason,
            reuse_completed=True,
        )
        return outcome

    async def prepare_chat_message_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        source_message_id: str,
        turn_id: str,
        source: str,
        event_type: str,
        runtime_turn_ids: Iterable[str] = (),
        runtime_replay_turn_ids: Iterable[str] = (),
        messages: list[dict[str, str]] | tuple[dict[str, str], ...] = (),
        surface_message_ids: Iterable[str] = (),
        reason: str = "user_delete_chat_message",
    ) -> ForgetOperation:
        """Persist a message-delete intent before blocking runtime delivery."""

        return await self._prepare_durable_forget(
            ForgetSelector.chat_message(
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                source_message_id=source_message_id,
                turn_id=turn_id,
                source=source,
                event_type=event_type,
                runtime_turn_ids=list(runtime_turn_ids),
                runtime_replay_turn_ids=list(runtime_replay_turn_ids),
                messages=messages,
                surface_message_ids=list(surface_message_ids),
            ),
            reason=reason,
            reuse_completed=True,
            execution_ready=False,
        )

    async def forget_chat_history_sources(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: Iterable[str],
        messages: list[dict[str, str]],
        surface_message_ids: Iterable[str],
        reason: str = "user_clear_chat_history",
    ) -> ForgetOutcome:
        """Forget the exact transcript snapshot while keeping the session reusable."""
        selector = ForgetSelector.chat_history(
            user_id=user_id,
            session_id=session_id,
            turn_ids=list(turn_ids),
            messages=messages,
            surface_message_ids=list(surface_message_ids),
        )
        outcome = await self._execute_durable_forget(
            selector,
            reason=reason,
            reuse_completed=True,
        )
        return outcome

    async def prepare_chat_history_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: Iterable[str],
        messages: list[dict[str, str]],
        surface_message_ids: Iterable[str],
        reason: str = "user_clear_chat_history",
    ) -> ForgetOperation:
        """Persist a history-clear intent before blocking runtime delivery."""

        return await self._prepare_durable_forget(
            ForgetSelector.chat_history(
                user_id=user_id,
                session_id=session_id,
                turn_ids=list(turn_ids),
                messages=messages,
                surface_message_ids=list(surface_message_ids),
            ),
            reason=reason,
            reuse_completed=True,
            execution_ready=False,
        )

    async def list_chat_forget_intents_awaiting_runtime_barriers(
        self,
    ) -> list[ForgetOperation]:
        """Return chat forget intents whose runtime scopes are not blocked yet."""

        return await self._durable_forget_runner.list_awaiting_chat_barriers()

    async def activate_chat_forget_intent(
        self,
        operation_id: str,
    ) -> ForgetOperation:
        """Activate a chat forget intent after its runtime barrier commits."""

        return await self._durable_forget_runner.activate(operation_id)

    async def execute_prepared_forget(self, operation_id: str) -> ForgetOutcome:
        """Execute one already durable forget intent under the clear barrier."""

        async with self._clear_barrier.operation():
            return await self._durable_forget_runner.execute_prepared(operation_id)

    async def list_pending_chat_surface_finalizations(self) -> list[ForgetOperation]:
        """Return completed chat forget operations whose chat rows remain."""
        return await self._durable_forget_runner.list_pending_surface_finalizations()

    async def list_completed_chat_forget_operations(
        self,
        *,
        limit: int = 1000,
        after_created_at: float | None = None,
        after_operation_id: str | None = None,
    ) -> list[ForgetOperation]:
        """Page completed chat deletion identities for barrier reconciliation."""

        return await self._durable_forget_runner.list_completed_chat_forget_operations(
            limit=limit,
            after_created_at=after_created_at,
            after_operation_id=after_operation_id,
        )

    async def mark_chat_surface_finalized(self, operation_id: str) -> None:
        """Persist that the chat-owned side of one durable forget completed."""
        await self._durable_forget_runner.mark_surface_finalized(operation_id)

    async def was_chat_session_forgotten(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> bool:
        """Return whether a prior session forget completed after chat rows vanished."""
        selector = ForgetSelector.chat_session(
            user_id=user_id,
            session_id=session_id,
            turn_ids=[],
        )
        return await self._durable_forget_runner.has_completed_selector(selector)

    async def forget_source_event(
        self,
        event_id: str,
        *,
        reason: str = "user_delete_event",
        block_source_item: bool = True,
    ) -> bool:
        normalized = normalize_source_event_ids([event_id])
        if not normalized or self.l1 is None:
            return False
        normalized_event_id = normalized[0]
        selector = ForgetSelector.known_events(
            [normalized_event_id],
            block_source_item=block_source_item,
        )
        async with self._clear_barrier.operation():
            event = await self.l1.get_event(normalized_event_id)
            if event is None and not await self._source_events_are_tombstoned(
                [normalized_event_id]
            ):
                return False
            await self._durable_forget_runner.execute(
                selector,
                reason=reason,
                reuse_completed=True,
            )
        return True

    async def forget_source_events(
        self,
        event_ids: Iterable[str],
        *,
        reason: str = "user_delete_event",
        block_source_item: bool = True,
    ) -> int:
        return await self.forget_known_source_events(
            event_ids,
            reason=reason,
            block_source_item=block_source_item,
        )

    async def forget_known_source_events(
        self,
        event_ids: Iterable[str],
        *,
        reason: str,
        block_source_item: bool = True,
    ) -> int:
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return 0
        selector = ForgetSelector.known_events(
            normalized,
            block_source_item=block_source_item,
        )
        outcome = await self._execute_durable_forget(
            selector,
            reason=reason,
            reuse_completed=True,
        )
        return outcome.event_count

    async def forget_entity_memory(
        self,
        *,
        entity_id: str,
        delete_l1_events: bool,
    ) -> dict[str, Any]:
        selector = ForgetSelector.entity(
            entity_id,
            delete_l1_events=delete_l1_events,
        )
        outcome = await self._execute_durable_forget(
            selector,
            reason="user_forget_entity",
            reuse_completed=False,
        )
        return {
            "l2_counts": outcome.target_result,
            "l1_events_deleted": outcome.event_count,
        }

    async def forget_time_range_memory(
        self,
        *,
        start: float,
        end: float,
        delete_l1_events: bool,
    ) -> dict[str, Any]:
        selector = ForgetSelector.time_range(
            start=start,
            end=end,
            delete_l1_events=delete_l1_events,
        )
        outcome = await self._execute_durable_forget(
            selector,
            reason="user_forget_time_range",
            reuse_completed=False,
        )
        return {
            "l2_counts": outcome.target_result,
            "l1_events_deleted": outcome.event_count,
        }

    async def forget_episode_memory(
        self,
        *,
        episode_id: str,
        delete_events: bool,
    ) -> dict[str, Any] | None:
        selector = ForgetSelector.episode(episode_id, delete_events=delete_events)
        async with self._clear_barrier.operation():
            if not await self._durable_forget_runner.episode_exists(episode_id):
                return None
            outcome = await self._durable_forget_runner.execute(
                selector,
                reason="user_forget_episode",
                reuse_completed=False,
            )
        return {**outcome.target_result, "l1_events_deleted": outcome.event_count}

    async def resume_pending_forget_operations(
        self,
        *,
        force: bool = False,
        fail_on_barrier_error: bool = False,
    ) -> dict[str, int]:
        async with self._clear_barrier.operation():
            return await self._durable_forget_runner.recover_pending(
                force=force,
                fail_on_barrier_error=fail_on_barrier_error,
            )

    async def _execute_durable_forget(
        self,
        selector: ForgetSelector,
        *,
        reason: str,
        reuse_completed: bool,
    ) -> ForgetOutcome:
        async with self._clear_barrier.operation():
            return await self._durable_forget_runner.execute(
                selector,
                reason=reason,
                reuse_completed=reuse_completed,
            )

    async def _prepare_durable_forget(
        self,
        selector: ForgetSelector,
        *,
        reason: str,
        reuse_completed: bool,
        execution_ready: bool = True,
    ) -> ForgetOperation:
        return await self._durable_forget_runner.prepare(
            selector,
            reason=reason,
            reuse_completed=reuse_completed,
            execution_ready=execution_ready,
        )

    async def _source_events_are_tombstoned(self, event_ids: Iterable[str]) -> bool:
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return False
        async with sqlite_connection_async(self.memory_db_path) as db:
            found = await source_event_tombstone_ids(db, normalized)
        return len(found) == len(normalized)

    async def _any_source_reference_is_tombstoned(self, event_ids: Iterable[str]) -> bool:
        """Return whether any replay identity has a durable delete barrier."""
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return False
        async with sqlite_connection_async(self.memory_db_path) as db:
            return bool(await source_event_tombstone_ids(db, normalized))


__all__ = ["UnifiedSourceEventForgettingMixin"]
