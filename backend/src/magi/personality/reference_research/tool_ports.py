"""Web-tool-backed ports for reference research."""

from __future__ import annotations

import uuid
from typing import Any

from ...agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from ...events.domain_payloads import TaskContext
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


class ToolReferenceSearchPort:
    """Search through the runtime web-search tool and its safety boundary."""

    def __init__(self, invocation_service: ToolInvocationService | None = None) -> None:
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


class ToolReferenceFetchPort:
    """Fetch through the runtime web-fetch tool and its network guards."""

    def __init__(self, invocation_service: ToolInvocationService | None = None) -> None:
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
            raise RuntimeError(str(getattr(result, "error", "Web fetch failed")))
        data = getattr(result, "data", None)
        return dict(data) if isinstance(data, dict) else {}


__all__ = ["ToolReferenceFetchPort", "ToolReferenceSearchPort"]
