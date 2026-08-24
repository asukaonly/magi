"""Execution coordinator for timeline task agents."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .contracts import (
    TimelineExecutionRequest,
    TimelineExecutionResult,
    TimelineAdmissionDecision,
    TimelineCapabilitySelection,
    TimelineRuntimeContext,
)


TimelineHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class TimelineExecutionCoordinator:
    """Coordinates timeline fact processing around an injected handler."""

    def __init__(self, timeline_handler: TimelineHandler | None = None) -> None:
        self._timeline_handler = timeline_handler

    async def admit_context(
        self,
        context: TimelineRuntimeContext,
    ) -> TimelineAdmissionDecision:
        _ = context
        return TimelineAdmissionDecision()

    async def resolve_capabilities(
        self,
        context: TimelineRuntimeContext,
        admission: TimelineAdmissionDecision,
    ) -> TimelineCapabilitySelection:
        _ = (context, admission)
        return TimelineCapabilitySelection()

    async def build_execution_request(
        self,
        context: TimelineRuntimeContext,
        admission: TimelineAdmissionDecision,
        capabilities: TimelineCapabilitySelection,
    ) -> TimelineExecutionRequest:
        return TimelineExecutionRequest(
            context=context,
            admission=admission,
            capabilities=capabilities,
            payload=context.latest_payload,
        )

    async def execute_request(
        self,
        request: TimelineExecutionRequest,
    ) -> TimelineExecutionResult:
        if self._timeline_handler is not None and request.payload is not None:
            await self._timeline_handler(request.payload.content)
        return TimelineExecutionResult(handled=True, payload=request.payload)
