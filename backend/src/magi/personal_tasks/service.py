"""One command boundary for personal items and external suggestions."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from uuid import NAMESPACE_URL, uuid5

from ..core.logger import get_logger

from .models import ItemPatch, MutationResult, TaskMutation, TaskNotFoundError, TaskReference
from .store import PersonalTaskStore

logger = get_logger(__name__)


class PersonalTaskService:
    def __init__(self, store: PersonalTaskStore) -> None:
        self.store = store
        self.lock = asyncio.Lock()
        self.on_changed: Callable[[], Awaitable[None]] | None = None
        self._clearing = False
        self._generation = 0

    async def mutate(
        self,
        user_id: str,
        command: TaskMutation,
        *,
        actor: str,
        references: list[TaskReference] | None = None,
    ) -> MutationResult:
        generation = self._generation
        if self._clearing:
            raise RuntimeError("Personal task writes are paused for data clearing")
        async with self.lock:
            if generation != self._generation:
                raise RuntimeError("Personal task operation crossed a data clear")
            result = await self.store.mutate(user_id, command, actor=actor, references=references)
        return await self._after_commit(user_id, result)

    async def propose(
        self,
        *,
        user_id: str,
        source_key: str,
        title: str,
        body_md: str,
        references: list[TaskReference],
    ) -> MutationResult:
        """Record an explicitly contributed source candidate without creating a commitment."""
        item_id = str(uuid5(NAMESPACE_URL, f"personal-task:{user_id}:{source_key}"))
        generation = self._generation
        if self._clearing:
            raise RuntimeError("Personal task writes are paused for data clearing")
        async with self.lock:
            if generation != self._generation:
                raise RuntimeError("Personal task proposal crossed a data clear")
            try:
                existing = await self.store.get(user_id, item_id)
            except TaskNotFoundError:
                existing = None
            if existing:
                # Source refresh must never overwrite user edits or acceptance.
                return MutationResult(item=existing.item, replayed=True)
            command = TaskMutation(
                request_id=f"source:{item_id}",
                action="create",
                fields=ItemPatch(title=title, body_md=body_md, status="inbox"),
            )
            result = await self.store.mutate(
                user_id,
                command,
                actor="source",
                references=references,
                origin="source",
                assigned_id=item_id,
            )
        return await self._after_commit(user_id, result)

    async def _after_commit(self, user_id: str, result: MutationResult) -> MutationResult:
        if self.on_changed:
            try:
                await self.on_changed()
            except Exception:
                # The mutation is already durable. Reconciliation retries independently;
                # never report a committed change as a failed write.
                logger.warning("Personal reminder reconciliation remains pending", exc_info=True)
                result.reminders_pending = True
        if result.item is not None:
            try:
                result.item = (await self.store.get(user_id, result.item.id)).item
            except TaskNotFoundError:
                result.deleted_ids = [result.item.id]
                result.item = None
        return result

    @asynccontextmanager
    async def user_content_clear_boundary(self):
        self._clearing = True
        try:
            async with self.lock:
                self._generation += 1
                yield
        finally:
            self._clearing = False


_service: PersonalTaskService | None = None


def bind_personal_task_service(service: PersonalTaskService | None) -> None:
    global _service
    _service = service


def get_personal_task_service() -> PersonalTaskService:
    if _service is None:
        raise RuntimeError("Personal task service is unavailable")
    return _service
