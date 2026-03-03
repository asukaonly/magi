"""
TaskAgent base abstraction for multi-instance runtime.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from ...core.logger import get_logger
from .contracts import FactRecord
from .types import TaskAgentType, build_task_agent_key, get_task_agent_type_value

logger = get_logger(__name__)


class TaskAgent:
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
        self._action_executor = None
        self._processed = 0
        self._enqueue_rejected = 0
        self._fact_memory: list[FactRecord] = []
        self._max_fact_memory = 200
        self._batch_size = 16

    async def start(self, action_executor) -> None:
        if self._running:
            return
        self._action_executor = action_executor
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

    async def build_context(self, merged_facts: list[FactRecord]) -> dict[str, Any]:
        """Build runtime context from merged facts."""
        latest_fact = merged_facts[-1] if merged_facts else None
        return {
            "latest_fact": latest_fact,
            "recent_facts": merged_facts[-20:],
            "agent_id": self.agent_id,
            "agent_type": get_task_agent_type_value(self.agent_type),
            "runtime_key": self.runtime_key,
        }

    async def match_intent(self, context: dict[str, Any]) -> dict[str, Any]:
        """Intent and complexity matching for model/tool path selection."""
        latest_fact = context.get("latest_fact")
        event_type = latest_fact.event_type if isinstance(latest_fact, FactRecord) else "unknown"
        return {"intent": event_type, "difficulty": "normal", "execution_mode": "llm"}

    async def match_tools(self, context: dict[str, Any], intent_result: dict[str, Any]) -> dict[str, Any]:
        """Tool matching step."""
        return {"tools": [], "reasoning": "default_no_tool"}

    async def assemble_llm_params(
        self,
        context: dict[str, Any],
        intent_result: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble model invocation parameters."""
        return {
            "context": context,
            "intent_result": intent_result,
            "tool_result": tool_result,
        }

    async def build_prompt_context(
        self,
        context: dict[str, Any],
        intent_result: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Build modular prompt context for reusable prompt assembly."""
        _ = (context, intent_result, tool_result)
        return None

    async def call_llm(self, context: dict[str, Any], llm_params: dict[str, Any]) -> Any:
        """Model/tool execution step."""
        return llm_params

    async def parse_result(self, context: dict[str, Any], raw_result: Any) -> None:
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
