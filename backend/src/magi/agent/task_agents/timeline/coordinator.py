"""Execution coordinator for timeline task agents."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .contracts import (
    TimelineExecutionRequest,
    TimelineExecutionResult,
    TimelineIntentDecision,
    TimelineRuntimeContext,
    TimelineToolSelection,
)


TimelineHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class TimelineExecutionCoordinator:
    """Coordinates timeline fact processing around an injected handler."""

    def __init__(self, timeline_handler: TimelineHandler | None = None) -> None:
        self._timeline_handler = timeline_handler

    async def match_intent(self, context: TimelineRuntimeContext) -> TimelineIntentDecision:
        _ = context
        return TimelineIntentDecision()

    async def match_tools(
        self,
        context: TimelineRuntimeContext,
        intent_result: TimelineIntentDecision,
    ) -> TimelineToolSelection:
        _ = (context, intent_result)
        return TimelineToolSelection()

    async def assemble_request(
        self,
        context: TimelineRuntimeContext,
        intent_result: TimelineIntentDecision,
        tool_result: TimelineToolSelection,
    ) -> TimelineExecutionRequest:
        return TimelineExecutionRequest(
            context=context,
            intent_result=intent_result,
            tool_result=tool_result,
            payload=context.latest_payload,
        )

    async def execute(self, request: TimelineExecutionRequest) -> TimelineExecutionResult:
        if self._timeline_handler is not None and request.payload is not None:
            await self._timeline_handler(request.payload.content)
        return TimelineExecutionResult(handled=True, payload=request.payload)
