"""Fallback final-response pass for function-calling execution."""

from __future__ import annotations

from typing import cast

from ....config.models import ThinkingDepth
from ...cancel import CancelToken
from magi.control.run_control import RunControl
from .fallback_flow import (
    FallbackExecutionContext,
    FallbackHostProtocol,
    execute_fallback_response_flow,
)
from .step_executor import FunctionCallingStepState
from .types import ExecutionOutcome

class FunctionCallingFallbackMixin:
    """Run the bounded no-tools fallback once the normal tool loop stops."""

    async def _execute_fallback_final_response(
        self,
        *,
        state: FunctionCallingStepState,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        user_id: str,
        session_id: str | None,
        session_run_id: str | None,
        session_run_revision: int,
        turn_id: str | None,
        execution_preset: str,
        execution_agent_id: str,
        execution_workspace: str | None,
        llm_timeout_seconds: float | None,
        final_response_json_mode: bool,
        final_response_reason: str = "max_iterations_reached",
        cancel_token: CancelToken | None = None,
        control: RunControl | None = None,
    ) -> ExecutionOutcome:
        """Run the no-tools finalization pass once the bounded loop stops."""
        host = cast(FallbackHostProtocol, self)
        context = FallbackExecutionContext(
            user_id=user_id,
            session_id=session_id,
            session_run_id=session_run_id,
            session_run_revision=session_run_revision,
            turn_id=turn_id,
            execution_preset=execution_preset,
            execution_agent_id=execution_agent_id,
            execution_workspace=execution_workspace,
            llm_timeout_seconds=llm_timeout_seconds,
            final_response_json_mode=final_response_json_mode,
            final_response_reason=final_response_reason,
            thinking_depth=thinking_depth,
            control=control,
        )
        return await execute_fallback_response_flow(
            host,
            state,
            context,
            cancel_token=cancel_token,
        )


__all__ = ["FunctionCallingFallbackMixin"]
