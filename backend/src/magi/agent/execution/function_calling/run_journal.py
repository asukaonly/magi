"""Durable journal projection for one function-calling run."""

from __future__ import annotations

import time
from typing import Any

from ....core.logger import get_logger
from ..context_fingerprint import (
    context_source_refs,
    effective_context_fingerprint,
    message_fingerprints,
    stable_hash,
)
from magi.runtime_trace.run_events import AgentRunEventType

from ..contracts import RunContextManifest
from ..journal import AgentRunJournal
from .run_input import AgentRunRequest
from .step_models import FunctionCallingStepState
from .types import ExecutionOutcome

logger = get_logger(__name__)


class FunctionCallingRunJournal:
    """Own journal creation and privacy-safe run-event projection."""

    def __init__(self, host: Any) -> None:
        self._host = host

    async def start(
        self,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
    ) -> None:
        log_fields = {
            "run_id": run_input.run_id,
            "parent_run_id": run_input.parent_run_id,
            "session_id": run_input.session_id,
            "turn_id": run_input.turn_id,
            "execution_preset": run_input.execution_preset,
            "execution_agent_id": run_input.execution_agent_id,
            "resumed": run_input.checkpoint is not None,
            "step_index": state.iteration,
            "max_iterations": run_input.max_iterations,
            "tool_count": len(state.selected_tool_names),
            "tool_names": list(state.selected_tool_names),
            "context_sources": _compact_context_sources(run_input.context_sources),
            "capability_rejections": list(
                run_input.capability_resolution.get("rejected_tools", [])
            ),
            "reasoning_preference": run_input.reasoning_policy.preference.value,
            "reasoning_requested": state.reasoning_state.requested_depth.value,
            "reasoning_effective": state.reasoning_state.effective_depth.value,
            "reasoning_maximum": run_input.reasoning_policy.maximum_depth.value,
            "reasoning_escalation_budget": run_input.reasoning_policy.max_escalations,
            "reasoning_escalation_step": run_input.reasoning_policy.escalation_step,
        }
        logger.info(
            "agent_run.resumed" if run_input.checkpoint is not None else "agent_run.started",
            **log_fields,
        )
        journal = AgentRunJournal(
            run_id=run_input.run_id,
            turn_id=run_input.turn_id,
            session_id=run_input.session_id,
            user_id=run_input.user_id,
            store=getattr(self._host, "runtime_trace_store", None),
        )
        state.journal = journal
        if run_input.checkpoint is not None:
            await journal.resume()
            await journal.append(
                AgentRunEventType.RUN_RESUMED,
                step_index=state.iteration,
                payload={
                    "checkpoint_reason": run_input.checkpoint.reason,
                    "checkpoint_note": run_input.checkpoint.note,
                    "reasoning_state": state.reasoning_state.to_dict(),
                    "repair_iterations": state.repair_iterations,
                    "evidence": [item.to_ref().to_dict() for item in state.tool_evidence],
                },
            )
            return

        tool_schema_hashes = {
            str(tool.get("function", {}).get("name") or ""): stable_hash(tool)
            for tool in state.tools
            if str(tool.get("function", {}).get("name") or "")
        }
        model_context = getattr(self._host, "_active_model_context", None)
        await journal.record_manifest(
            RunContextManifest(
                run_id=run_input.run_id,
                turn_id=run_input.turn_id,
                session_id=run_input.session_id,
                user_id=run_input.user_id,
                prompt_assembly_version="unified-agent-v1",
                system_prompt_hash=stable_hash(state.effective_system_prompt),
                system_prompt_size_bytes=len(state.effective_system_prompt.encode("utf-8")),
                message_fingerprints=message_fingerprints(state.messages),
                tool_catalog=tuple(state.selected_tool_names),
                tool_schema_hashes=tool_schema_hashes,
                context_source_refs=context_source_refs(run_input.context_sources),
                provider=str(getattr(model_context, "provider_id", "unknown")),
                model=str(getattr(model_context, "model_id", "unknown")),
                reasoning_policy=run_input.reasoning_policy.to_dict(),
                created_at_ms=int(time.time() * 1000),
            )
        )
        await journal.append(
            AgentRunEventType.RUN_STARTED,
            payload={
                "execution_preset": run_input.execution_preset,
                "parent_run_id": run_input.parent_run_id,
            },
        )
        await journal.append(
            AgentRunEventType.CONTEXT_PREPARED,
            payload={
                "message_count": len(state.messages),
                "tool_count": len(state.selected_tool_names),
            },
        )
        await journal.append(
            AgentRunEventType.CAPABILITIES_RESOLVED,
            payload=dict(run_input.capability_resolution),
        )
        await journal.append(
            AgentRunEventType.REASONING_POLICY_RESOLVED,
            payload={
                **run_input.reasoning_policy.to_dict(),
                **state.reasoning_state.to_dict(),
            },
        )

    async def record_effective_context(
        self,
        state: FunctionCallingStepState,
        *,
        mode: str,
        step_index: int,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> None:
        if state.journal is None:
            return
        await state.journal.append(
            AgentRunEventType.CONTEXT_PREPARED,
            step_index=step_index,
            payload=effective_context_fingerprint(
                mode=mode,
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                reasoning_state=(
                    state.reasoning_state.to_dict() if state.reasoning_state is not None else {}
                ),
            ),
        )

    async def record_terminal(
        self,
        state: FunctionCallingStepState,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcome:
        reasoning_state = state.reasoning_state
        logger.info(
            "agent_run.terminal",
            run_id=state.run_id,
            status=outcome.status,
            failure_reason=outcome.failure_reason,
            iterations=outcome.iterations,
            repair_iterations=state.repair_iterations,
            evidence_count=len(state.tool_evidence),
            successful_evidence_count=sum(1 for item in state.tool_evidence if item.success),
            tool_failure_count=len(state.tool_failures),
            reasoning_requested=(
                reasoning_state.requested_depth.value if reasoning_state is not None else None
            ),
            reasoning_effective=(
                reasoning_state.effective_depth.value if reasoning_state is not None else None
            ),
            reasoning_escalations=(
                reasoning_state.escalation_count if reasoning_state is not None else 0
            ),
        )
        if state.journal is None:
            return outcome
        event_type = {
            "completed": AgentRunEventType.RUN_COMPLETED,
            "cancelled": AgentRunEventType.RUN_CANCELLED,
            "suspended": AgentRunEventType.RUN_SUSPENDED,
            "detached": AgentRunEventType.RUN_SUSPENDED,
            "blocked": AgentRunEventType.RUN_BLOCKED,
        }.get(outcome.status, AgentRunEventType.RUN_FAILED)
        await state.journal.append(
            event_type,
            step_index=state.iteration,
            payload={
                "status": outcome.status,
                "failure_reason": outcome.failure_reason,
                "evidence": [item.to_ref().to_dict() for item in state.tool_evidence],
                "reasoning_state": (
                    state.reasoning_state.to_dict() if state.reasoning_state is not None else {}
                ),
            },
        )
        return outcome


def _compact_context_sources(
    sources: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Return privacy-safe context availability fields for diagnostics."""

    compact: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        item = {
            key: source.get(key)
            for key in (
                "provider",
                "availability",
                "implicit_retrieval",
                "query_capability",
                "preset",
                "ownership",
            )
            if source.get(key) is not None
        }
        if item:
            compact.append(item)
    return compact


__all__ = ["FunctionCallingRunJournal"]
