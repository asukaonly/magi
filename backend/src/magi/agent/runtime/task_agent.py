"""TaskAgent base abstraction for multi-instance runtime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, Optional, TypeVar, cast

from ...core.logger import get_logger
from ..execution.task_budget import fresh_task_execution_budget_context
from .contracts import FactRecord
from .types import TaskAgentType, build_task_agent_key, get_task_agent_type_value

logger = get_logger(__name__)


class TaskAgentBatchDiscarded(Exception):
    """Stop one transferred batch without treating it as an execution failure."""


class FactQueue:
    """Bounded FIFO queue with explicit inspection and filtering operations."""

    def __init__(self, maxsize: int = 0) -> None:
        self.maxsize = max(0, int(maxsize))
        self._items: deque[FactRecord] = deque()

    def qsize(self) -> int:
        """Return the number of queued facts."""

        return len(self._items)

    def empty(self) -> bool:
        """Return whether no facts are queued."""

        return not self._items

    def full(self) -> bool:
        """Return whether the configured positive capacity is exhausted."""

        return self.maxsize > 0 and len(self._items) >= self.maxsize

    def put_nowait(self, fact: FactRecord) -> None:
        """Append a fact or raise when the bounded queue is full."""

        if self.full():
            raise asyncio.QueueFull
        self._items.append(fact)

    def get_nowait(self) -> FactRecord:
        """Remove and return the oldest fact without waiting."""

        try:
            return self._items.popleft()
        except IndexError as exc:
            raise asyncio.QueueEmpty from exc

    def peek_nowait(self) -> FactRecord:
        """Return the oldest fact without removing it."""

        try:
            return self._items[0]
        except IndexError as exc:
            raise asyncio.QueueEmpty from exc

    def snapshot(self) -> tuple[FactRecord, ...]:
        """Return an immutable FIFO snapshot."""

        return tuple(self._items)

    def remove_if(
        self,
        predicate: Callable[[FactRecord], bool],
    ) -> tuple[FactRecord, ...]:
        """Remove matching facts while preserving the order of all others."""

        kept: deque[FactRecord] = deque()
        removed: list[FactRecord] = []
        for fact in self._items:
            if predicate(fact):
                removed.append(fact)
            else:
                kept.append(fact)
        self._items = kept
        return tuple(removed)


@dataclass(slots=True)
class TaskAgentRuntimeContext:
    """Base runtime context produced by the shared task-agent loop."""

    latest_fact: Optional[FactRecord]
    recent_facts: list[FactRecord]
    agent_id: str
    agent_type: str
    runtime_key: str


@dataclass(slots=True)
class TaskAgentAdmissionDecision:
    """Minimal deterministic admission result for non-specialized task agents."""

    run_kind: str
    execution_mode: str = "llm"


@dataclass(slots=True)
class TaskAgentCapabilitySelection:
    """Minimal capability-selection result for non-specialized task agents."""

    tools: list[str] = field(default_factory=list)
    reasoning: str = "default_no_tool"


@dataclass(slots=True)
class TaskAgentExecutionRequest:
    """Minimal typed execution payload for the default task-agent pipeline."""

    context: TaskAgentRuntimeContext
    admission: TaskAgentAdmissionDecision
    capabilities: TaskAgentCapabilitySelection


@dataclass(frozen=True, slots=True)
class FactAdmissionResult:
    """Outcome of conditionally admitting one fact into an agent queue."""

    queued: bool
    superseded: bool = False


ContextT = TypeVar("ContextT")
AdmissionT = TypeVar("AdmissionT")
CapabilitiesT = TypeVar("CapabilitiesT")
RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class TaskAgent(Generic[ContextT, AdmissionT, CapabilitiesT, RequestT, ResultT]):
    """Self-looping task agent instance with its own fact queue."""

    def __init__(
        self,
        agent_type: TaskAgentType | str,
        agent_id: str,
        queue_maxsize: int = 100,
        enqueue_timeout_ms: float = 100.0,
    ) -> None:
        self.agent_type = agent_type
        self.agent_id = agent_id
        self.runtime_key = build_task_agent_key(agent_type, agent_id)
        self._queue_maxsize = queue_maxsize
        self._enqueue_timeout_ms = enqueue_timeout_ms
        self._fact_queue = FactQueue(maxsize=queue_maxsize)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._event_emitter = None
        self._processed = 0
        self._failed = 0
        self._enqueue_rejected = 0
        self._fact_transfer_lock = asyncio.Lock()
        self._facts_available = asyncio.Event()
        self._queue_space_available = asyncio.Event()
        self._queue_space_available.set()
        self._active_batch_facts: list[FactRecord] = []
        self._fact_memory: list[FactRecord] = []
        self._max_fact_memory = 200
        self._batch_size = 16
        self._task_agent_manager = None
        self._source_hub = None

    async def start(self, event_emitter, task_agent_manager=None, source_hub=None) -> None:
        if self._running:
            return
        self._event_emitter = event_emitter
        self._task_agent_manager = task_agent_manager
        self._source_hub = source_hub
        self._running = True
        if not self._fact_queue.empty():
            self._facts_available.set()
        with fresh_task_execution_budget_context():
            self._task = asyncio.create_task(self._run_loop())
        logger.info(f"TaskAgent started | key={self.runtime_key}")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._task_agent_manager = None
        self._source_hub = None
        logger.info(f"TaskAgent stopped | key={self.runtime_key}")

    async def add_fact(self, fact: FactRecord) -> bool:
        """Add fact to queue with timeout. Returns True if successful, False if rejected."""
        result = await self._enqueue_fact(fact)
        return result.queued

    async def add_fact_with_admission(
        self,
        fact: FactRecord,
        *,
        admit: Callable[[], Awaitable[bool]],
    ) -> FactAdmissionResult:
        """Conditionally persist admission immediately before queue insertion."""

        return await self._enqueue_fact(fact, admit=admit)

    async def _enqueue_fact(
        self,
        fact: FactRecord,
        *,
        admit: Callable[[], Awaitable[bool]] | None = None,
    ) -> FactAdmissionResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (self._enqueue_timeout_ms / 1000.0)
        try:
            while True:
                async with self._fact_transfer_lock:
                    if self._fact_queue.full():
                        self._queue_space_available.clear()
                    else:
                        admission_cancelled = False
                        if admit is not None:
                            admission_task = asyncio.create_task(admit())
                            while not admission_task.done():
                                try:
                                    await asyncio.shield(admission_task)
                                except asyncio.CancelledError:
                                    if admission_task.cancelled():
                                        break
                                    admission_cancelled = True
                                    if admission_task.done():
                                        break
                            if not admission_task.result():
                                if admission_cancelled:
                                    raise asyncio.CancelledError
                                return FactAdmissionResult(
                                    queued=False,
                                    superseded=True,
                                )
                        self._fact_queue.put_nowait(fact)
                        self._facts_available.set()
                        if self._fact_queue.full():
                            self._queue_space_available.clear()
                        if admission_cancelled:
                            raise asyncio.CancelledError
                        return FactAdmissionResult(queued=True)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                await asyncio.wait_for(
                    self._queue_space_available.wait(),
                    timeout=remaining,
                )
        except (asyncio.TimeoutError, asyncio.QueueFull):
            self._enqueue_rejected += 1
            logger.warning(
                f"TaskAgent queue full, fact rejected | key={self.runtime_key} "
                f"queue_size={self._fact_queue.qsize()} max={self._queue_maxsize}"
            )
            return FactAdmissionResult(queued=False)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._facts_available.wait()
                batch = await self._take_next_batch()
            except asyncio.CancelledError:
                raise
            if not batch:
                continue
            stage = "merge_facts"
            context: ContextT | None = None
            try:
                facts = await self.merge_facts(batch)
                if facts:
                    stage = "build_context"
                    context = await self.build_context(facts)
                    async with self.execution_scope(context):
                        stage = "admit_context"
                        admission = await self.admit_context(context)
                        stage = "resolve_capabilities"
                        capabilities = await self.resolve_capabilities(context, admission)
                        stage = "build_execution_request"
                        request = await self.build_execution_request(
                            context,
                            admission,
                            capabilities,
                        )
                        stage = "execute_request"
                        result = await self.execute_request(context, request)
                    stage = "finalize_result"
                    await self.finalize_result(context, result)
            except asyncio.CancelledError:
                raise
            except TaskAgentBatchDiscarded:
                pass
            except Exception as exc:
                self._failed += len(batch)
                logger.error(
                    f"TaskAgent handle_fact failed | key={self.runtime_key} "
                    f"stage={stage} error={exc}",
                    exc_info=True,
                )
                try:
                    await self.handle_batch_failure(
                        batch,
                        error=exc,
                        stage=stage,
                        context=context,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as failure_exc:
                    logger.error(
                        f"TaskAgent failure finalization failed | key={self.runtime_key} "
                        f"stage={stage} error={failure_exc}",
                        exc_info=True,
                    )
            finally:
                self._active_batch_facts = []
            self._processed += len(batch)

    async def _take_next_batch(self) -> list[FactRecord]:
        """Atomically transfer queued facts into the active batch."""

        async with self._fact_transfer_lock:
            batch: list[FactRecord] = []
            while len(batch) < self._batch_size:
                try:
                    next_fact = self._fact_queue.peek_nowait()
                except asyncio.QueueEmpty:
                    break
                if batch and self._should_end_batch_before(batch, next_fact):
                    break
                try:
                    batch.append(self._fact_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if self._fact_queue.empty():
                self._facts_available.clear()
            if not self._fact_queue.full():
                self._queue_space_available.set()
            self._active_batch_facts = list(batch)
            return batch

    def _should_end_batch_before(
        self,
        batch: list[FactRecord],
        next_fact: FactRecord,
    ) -> bool:
        """Return whether the next queued fact must start a later batch."""

        _ = (batch, next_fact)
        return False

    async def handle_fact(self, fact: FactRecord) -> None:
        raise NotImplementedError

    async def handle_batch_failure(
        self,
        batch: list[FactRecord],
        *,
        error: BaseException,
        stage: str,
        context: ContextT | None,
    ) -> None:
        """Finalize one failed batch without replaying potentially effectful work."""

        _ = (batch, error, stage, context)

    def snapshot_inflight_facts(self) -> tuple[FactRecord, ...]:
        """Return the current batch followed by facts still waiting in the queue."""
        return (*self._active_batch_facts, *self._fact_queue.snapshot())

    def has_inflight_work(self) -> bool:
        """Return whether this instance owns queued or actively executing work."""

        return (
            self._fact_transfer_lock.locked()
            or bool(self._active_batch_facts)
            or not self._fact_queue.empty()
        )

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        """Merge new facts with in-memory context and return working set."""
        self._fact_memory.extend(new_facts)
        if len(self._fact_memory) > self._max_fact_memory:
            self._fact_memory = self._fact_memory[-self._max_fact_memory :]
        return list(self._fact_memory)

    async def build_context(self, merged_facts: list[FactRecord]) -> ContextT:
        """Build runtime context from merged facts."""
        latest_fact = merged_facts[-1] if merged_facts else None
        return cast(
            ContextT,
            TaskAgentRuntimeContext(
                latest_fact=latest_fact,
                recent_facts=merged_facts[-20:],
                agent_id=self.agent_id,
                agent_type=get_task_agent_type_value(self.agent_type),
                runtime_key=self.runtime_key,
            ),
        )

    @asynccontextmanager
    async def execution_scope(self, context: ContextT) -> AsyncIterator[None]:
        """Bind resources shared by the model-facing stages of one admission."""
        _ = context
        yield

    async def admit_context(self, context: ContextT) -> AdmissionT:
        """Apply deterministic admission policy to the prepared context."""
        latest_fact = getattr(context, "latest_fact", None)
        event_type = latest_fact.event_type if isinstance(latest_fact, FactRecord) else "unknown"
        return cast(
            AdmissionT,
            TaskAgentAdmissionDecision(run_kind=event_type),
        )

    async def resolve_capabilities(
        self,
        context: ContextT,
        admission: AdmissionT,
    ) -> CapabilitiesT:
        """Resolve the capabilities available to the admitted execution."""
        _ = (context, admission)
        return cast(
            CapabilitiesT,
            TaskAgentCapabilitySelection(),
        )

    async def build_execution_request(
        self,
        context: ContextT,
        admission: AdmissionT,
        capabilities: CapabilitiesT,
    ) -> RequestT:
        """Build the typed request consumed by the domain executor."""
        return cast(
            RequestT,
            TaskAgentExecutionRequest(
                context=cast(TaskAgentRuntimeContext, context),
                admission=cast(TaskAgentAdmissionDecision, admission),
                capabilities=cast(TaskAgentCapabilitySelection, capabilities),
            ),
        )

    async def execute_request(self, context: ContextT, request: RequestT) -> ResultT:
        """Execute one admitted domain request."""
        _ = context
        return cast(ResultT, request)

    async def finalize_result(self, context: ContextT, result: ResultT) -> None:
        """Project and emit the terminal domain result."""
        _ = (context, result)

    def get_stats(self) -> dict:
        return {
            "agent_type": get_task_agent_type_value(self.agent_type),
            "agent_id": self.agent_id,
            "runtime_key": self.runtime_key,
            "queue_size": self._fact_queue.qsize(),
            "queue_maxsize": self._queue_maxsize,
            "processed": self._processed,
            "failed": self._failed,
            "enqueue_rejected": self._enqueue_rejected,
            "running": self._running,
            "busy": self.has_inflight_work(),
        }
