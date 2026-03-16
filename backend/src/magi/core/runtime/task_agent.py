"""
TaskAgent base abstraction for multi-instance runtime.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Generic, Optional, TypeVar, cast

from ...core.logger import get_logger
from .contracts import FactRecord
from .types import TaskAgentType, build_task_agent_key, get_task_agent_type_value

logger = get_logger(__name__)


@dataclass(slots=True)
class TaskAgentRuntimeContext:
    """Base runtime context produced by the shared task-agent loop."""

    latest_fact: Optional[FactRecord]
    recent_facts: list[FactRecord]
    agent_id: str
    agent_type: str
    runtime_key: str


@dataclass(slots=True)
class TaskAgentIntentResult:
    """Minimal typed intent result for non-specialized task agents."""

    intent: str
    difficulty: str = "normal"
    execution_mode: str = "llm"


@dataclass(slots=True)
class TaskAgentToolSelection:
    """Minimal typed tool-selection result for non-specialized task agents."""

    tools: list[str] = field(default_factory=list)
    reasoning: str = "default_no_tool"


@dataclass(slots=True)
class TaskAgentExecutionRequest:
    """Minimal typed execution payload for the default task-agent pipeline."""

    context: TaskAgentRuntimeContext
    intent_result: TaskAgentIntentResult
    tool_result: TaskAgentToolSelection


ContextT = TypeVar("ContextT")
IntentT = TypeVar("IntentT")
ToolSelectionT = TypeVar("ToolSelectionT")
RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class TaskAgent(Generic[ContextT, IntentT, ToolSelectionT, RequestT, ResultT]):
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
        self._fact_queue: asyncio.Queue[FactRecord] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._action_emitter = None
        self._processed = 0
        self._enqueue_rejected = 0
        self._fact_memory: list[FactRecord] = []
        self._max_fact_memory = 200
        self._batch_size = 16

    async def start(self, action_emitter) -> None:
        if self._running:
            return
        self._action_emitter = action_emitter
        self._running = True
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
        logger.info(f"TaskAgent stopped | key={self.runtime_key}")

    async def add_fact(self, fact: FactRecord) -> bool:
        """Add fact to queue with timeout. Returns True if successful, False if rejected."""
        try:
            timeout_seconds = self._enqueue_timeout_ms / 1000.0
            await asyncio.wait_for(self._fact_queue.put(fact), timeout=timeout_seconds)
            return True
        except asyncio.TimeoutError:
            self._enqueue_rejected += 1
            logger.warning(
                f"TaskAgent queue full, fact rejected | key={self.runtime_key} "
                f"queue_size={self._fact_queue.qsize()} max={self._queue_maxsize}"
            )
            return False
        except asyncio.QueueFull:
            self._enqueue_rejected += 1
            logger.warning(
                f"TaskAgent queue full, fact rejected | key={self.runtime_key}"
            )
            return False

    async def _run_loop(self) -> None:
        while self._running:
            try:
                first = await asyncio.wait_for(self._fact_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            batch = [first]
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._fact_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                facts = await self.merge_facts(batch)
                context = await self.build_context(facts)
                intent_result = await self.match_intent(context)
                tool_result = await self.match_tools(context, intent_result)
                llm_params = await self.assemble_llm_params(context, intent_result, tool_result)
                raw_result = await self.call_llm(context, llm_params)
                await self.parse_result(context, raw_result)
            except Exception as exc:
                logger.error(
                    f"TaskAgent handle_fact failed | key={self.runtime_key} "
                    f"error={exc}",
                    exc_info=True,
                )
            self._processed += len(batch)

    async def handle_fact(self, fact: FactRecord) -> None:
        raise NotImplementedError

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

    async def match_intent(self, context: ContextT) -> IntentT:
        """Intent and complexity matching for model/tool path selection."""
        latest_fact = getattr(context, "latest_fact", None)
        event_type = latest_fact.event_type if isinstance(latest_fact, FactRecord) else "unknown"
        return cast(
            IntentT,
            TaskAgentIntentResult(intent=event_type),
        )

    async def match_tools(self, context: ContextT, intent_result: IntentT) -> ToolSelectionT:
        """Tool matching step."""
        _ = (context, intent_result)
        return cast(
            ToolSelectionT,
            TaskAgentToolSelection(),
        )

    async def assemble_llm_params(
        self,
        context: ContextT,
        intent_result: IntentT,
        tool_result: ToolSelectionT,
    ) -> RequestT:
        """Assemble model invocation parameters."""
        return cast(
            RequestT,
            TaskAgentExecutionRequest(
                context=cast(TaskAgentRuntimeContext, context),
                intent_result=cast(TaskAgentIntentResult, intent_result),
                tool_result=cast(TaskAgentToolSelection, tool_result),
            ),
        )

    async def build_prompt_context(
        self,
        context: ContextT,
        intent_result: IntentT,
        tool_result: ToolSelectionT,
    ) -> Optional[object]:
        """Build modular prompt context for reusable prompt assembly."""
        _ = (context, intent_result, tool_result)
        return None

    async def call_llm(self, context: ContextT, llm_params: RequestT) -> ResultT:
        """Model/tool execution step."""
        _ = context
        return cast(ResultT, llm_params)

    async def parse_result(self, context: ContextT, raw_result: ResultT) -> None:
        """Parse and emit final result."""
        _ = (context, raw_result)

    def get_stats(self) -> dict:
        return {
            "agent_type": get_task_agent_type_value(self.agent_type),
            "agent_id": self.agent_id,
            "runtime_key": self.runtime_key,
            "queue_size": self._fact_queue.qsize(),
            "queue_maxsize": self._queue_maxsize,
            "processed": self._processed,
            "enqueue_rejected": self._enqueue_rejected,
            "running": self._running,
        }
