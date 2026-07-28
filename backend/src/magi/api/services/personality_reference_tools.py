"""Runtime-tool adapters for personality reference research."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from ...agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from ...events.domain_payloads import TaskContext
from ...personality.reference_research.ports import (
    ReferenceFetchError,
    ReferenceFetchPort,
    ReferenceSearchPort,
)
from ...tools.registry import tool_registry
from ...tools.schema import ToolExecutionContext


def _invocation_context(task_id: str) -> InvocationContext:
    turn_id = f"persona-reference-{task_id}"
    return InvocationContext(
        tool_category="web",
        task_context=TaskContext(
            session_id="persona_generation",
            turn_id=turn_id,
            task_id=task_id,
            user_id=None,
        ),
        execution_context=ToolExecutionContext(
            agent_id="personality_generation",
            task_id=task_id,
            workspace=".",
            permissions=[],
            env_vars={"trace_tool_call_id": str(uuid.uuid4())},
        ),
    )


class _ToolInvocationPort(Protocol):
    async def invoke(self, call: ToolCall, ctx: InvocationContext) -> Any:
        """Invoke one governed runtime tool call."""


class ToolReferenceSearchAdapter(ReferenceSearchPort):
    """Adapt the runtime web-search tool to the personality search port."""

    def __init__(self, invocation_service: _ToolInvocationPort | None = None) -> None:
        self._service = invocation_service or ToolInvocationService(tool_registry)

    async def search(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        task_id = str(uuid.uuid4())
        result = await self._service.invoke(
            ToolCall(name="web-search", args={"query": query, "num_results": limit}),
            _invocation_context(task_id),
        )
        if not bool(getattr(result, "success", False)):
            raise RuntimeError(str(getattr(result, "error", "Web search failed")))
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return []
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            return []
        return [item for item in raw_results if isinstance(item, dict)][:limit]


class ToolReferenceFetchAdapter(ReferenceFetchPort):
    """Adapt the runtime web-fetch tool to the personality fetch port."""

    def __init__(self, invocation_service: _ToolInvocationPort | None = None) -> None:
        self._service = invocation_service or ToolInvocationService(tool_registry)

    async def fetch(self, url: str, *, max_chars: int = 12000) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        result = await self._service.invoke(
            ToolCall(
                name="web-fetch",
                args={
                    "url": url,
                    "output_format": "markdown",
                    "include_metadata": True,
                    "max_chars": max_chars,
                },
            ),
            _invocation_context(task_id),
        )
        if not bool(getattr(result, "success", False)):
            data = getattr(result, "data", None)
            reason_code = (
                str(data.get("reason_code"))
                if isinstance(data, dict) and data.get("reason_code")
                else None
            )
            raise ReferenceFetchError(
                str(getattr(result, "error", "Web fetch failed")),
                code=reason_code,
            )
        data = getattr(result, "data", None)
        return dict(data) if isinstance(data, dict) else {}


__all__ = ["ToolReferenceFetchAdapter", "ToolReferenceSearchAdapter"]
