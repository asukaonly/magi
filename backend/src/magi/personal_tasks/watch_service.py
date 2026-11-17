"""Quiet condition checks with explicit scope, evidence and bounded model usage."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import AsyncContextManager, Protocol

from pydantic import BaseModel, ConfigDict

from ..core.logger import get_logger
from .models import TaskNotFoundError
from .service import PersonalTaskService
from .watch_models import (
    AttentionWatch,
    WatchDecision,
    WatchMutation,
    WatchMutationResult,
    WatchPage,
)
from .watch_store import watch_from_row

logger = get_logger(__name__)


class WatchMemoryBoundary(Protocol):
    def memory_operation_epoch(self) -> int: ...
    def memory_operation_guard(self) -> AsyncContextManager[None]: ...


class WatchEvidencePort(Protocol):
    memory: WatchMemoryBoundary

    def digest(self, event: dict) -> str: ...
    async def current(self, user_id: str, identities: list[str]) -> list[dict]: ...
    async def governance_revision(self) -> str: ...
    async def watch_sources(self, user_id: str) -> list[str]: ...
    async def watch_changes(
        self, user_id: str, sources: list[str], after: float, after_id: str
    ) -> tuple[list[dict], float, str]: ...


class WatchVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool


class AttentionWatchService:
    def __init__(
        self,
        tasks: PersonalTaskService,
        evidence: WatchEvidencePort,
        generate: Callable[[str, bool], Awaitable[str]],
        authorize: Callable[[str, str, str, str], Awaitable[bool]] | None = None,
    ) -> None:
        self.tasks = tasks
        self.evidence = evidence
        self.generate = generate
        self.authorize = authorize
        self._tick_lock = asyncio.Lock()

    async def mutate(self, user_id: str, command: WatchMutation) -> WatchMutationResult:
        generation = self.tasks._generation
        if self.tasks._clearing:
            raise RuntimeError("Attention watch writes are paused for data clearing")
        if command.fields:
            sources = await self.evidence.watch_sources(user_id)
            if not set(command.fields.sources).issubset(sources):
                raise ValueError(
                    "Choose sources with authorized saved material before creating a watch"
                )
        if generation != self.tasks._generation:
            raise RuntimeError("Attention watch operation crossed a data clear")
        result = await self.tasks.mutate_watch(user_id, command)
        if result.watch:
            try:
                result.watch = await self.get(user_id, result.watch.id)
            except TaskNotFoundError:
                result.watch = None
        return result

    async def _valid(self, row: dict) -> AttentionWatch:
        if row["result_json"]:
            expected = json.loads(row["evidence_json"])
            current = {
                event["event_id"]: self.evidence.digest(event)
                for event in await self.evidence.current(row["user_id"], list(expected))
            }
            if (
                current != expected
                or row["governance_revision"] != await self.evidence.governance_revision()
            ):
                await self.tasks.store.invalidate_watch_result(row)
                row = dict(row, result_json=None, check_status="invalidated")
        return watch_from_row(row)

    async def page(self, user_id: str, offset: int = 0) -> WatchPage:
        async with self.tasks.lock, self.evidence.memory.memory_operation_guard():
            await self.tasks.store.expire_watches(user_id)
            rows = await self.tasks.store.watch_rows(user_id, offset=offset)
            return WatchPage(
                items=[await self._valid(row) for row in rows[:50]],
                sources=await self.evidence.watch_sources(user_id),
                next_offset=offset + 50 if len(rows) > 50 else None,
            )

    async def get(self, user_id: str, identity: str) -> AttentionWatch:
        async with self.tasks.lock, self.evidence.memory.memory_operation_guard():
            await self.tasks.store.expire_watches(user_id)
            return await self._valid(await self.tasks.store.watch_row(user_id, identity))

    async def tick(self, user_id: str) -> None:
        if self._tick_lock.locked() or self.tasks._clearing:
            return
        async with self._tick_lock:
            await self.tasks.store.expire_watches(user_id)
            for row in await self.tasks.store.active_watch_rows(user_id):
                if row["last_checked_at"] and time.time() - row["last_checked_at"] < 3600:
                    continue
                try:
                    await self.evaluate(row)
                except Exception:
                    logger.warning(
                        "Attention watch check failed", watch_id=row["id"], exc_info=True
                    )

    async def evaluate(self, row: dict) -> None:
        memory = self.evidence.memory
        epoch = memory.memory_operation_epoch()
        async with self.tasks.lock, memory.memory_operation_guard():
            if self.tasks._clearing:
                return
            await self.tasks.store.expire_watches(row["user_id"])
            current = await self.tasks.store.watch_row(row["user_id"], row["id"])
            if current["version"] != row["version"] or current["status"] != "active":
                return
            watch = watch_from_row(row)
            events, cursor_time, cursor_id = await self.evidence.watch_changes(
                row["user_id"], watch.sources, row["cursor_time"], row["cursor_id"]
            )
            revision = await self.evidence.governance_revision()
            if not events:
                await self.tasks.store.finish_watch_check(
                    row,
                    cursor_time=cursor_time,
                    cursor_id=cursor_id,
                    result=None,
                    evidence={},
                    governance=revision,
                    check_status="no_match",
                )
                return
            if not await self.tasks.store.reserve_watch_check(row):
                return
            snapshot = {event["event_id"]: self.evidence.digest(event) for event in events}
        prompt = json.dumps(
            {
                "condition": watch.condition,
                "evidence": [
                    {
                        "event_id": event["event_id"],
                        "source": event["source"],
                        "content": event["content"][:2500],
                    }
                    for event in events
                ],
            },
            ensure_ascii=False,
        )
        try:
            decision = WatchDecision.model_validate_json(
                await asyncio.wait_for(self.generate(prompt, False), 90)
            )
            by_id = {event["event_id"]: event for event in events}
            if any(
                c.event_id not in by_id or c.quote not in by_id[c.event_id]["content"][:2500]
                for c in decision.citations
            ):
                raise ValueError("Watch result contains unsupported citations")
            if decision.matched:
                review = WatchVerification.model_validate_json(
                    await asyncio.wait_for(
                        self.generate(
                            json.dumps(
                                {
                                    "input": json.loads(prompt),
                                    "proposed_result": decision.model_dump(),
                                },
                                ensure_ascii=False,
                            ),
                            True,
                        ),
                        60,
                    )
                )
                if not review.supported:
                    raise ValueError("Watch result did not pass evidence review")
            async with self.tasks.lock, memory.memory_operation_guard():
                if epoch != memory.memory_operation_epoch() or self.tasks._clearing:
                    return
                await self.tasks.store.expire_watches(row["user_id"])
                current = await self.tasks.store.watch_row(row["user_id"], row["id"])
                if current["version"] != row["version"] or current["status"] != "active":
                    return
                current_evidence = {
                    event["event_id"]: self.evidence.digest(event)
                    for event in await self.evidence.current(row["user_id"], list(snapshot))
                }
                if (
                    current_evidence != snapshot
                    or revision != await self.evidence.governance_revision()
                ):
                    await self.tasks.store.finish_watch_check(
                        row,
                        cursor_time=row["cursor_time"],
                        cursor_id=row["cursor_id"],
                        result=None,
                        evidence={},
                        governance=revision,
                        check_status="invalidated",
                    )
                    return
                await self.tasks.store.finish_watch_check(
                    row,
                    cursor_time=cursor_time,
                    cursor_id=cursor_id,
                    result=decision.model_dump_json() if decision.matched else None,
                    evidence={c.event_id: snapshot[c.event_id] for c in decision.citations},
                    governance=revision,
                    check_status="matched" if decision.matched else "no_match",
                )
        except TaskNotFoundError:
            return
        except Exception:
            await self.tasks.store.finish_watch_check(
                row,
                cursor_time=row["cursor_time"],
                cursor_id=row["cursor_id"],
                result=None,
                evidence={},
                governance=revision,
                check_status="failed",
            )
            raise


_service: AttentionWatchService | None = None


def bind_attention_watch_service(service: AttentionWatchService | None) -> None:
    global _service
    _service = service


def get_attention_watch_service() -> AttentionWatchService:
    if _service is None:
        raise RuntimeError("Attention watch service is unavailable")
    return _service
