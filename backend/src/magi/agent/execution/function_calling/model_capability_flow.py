"""Model-capability admission and attachment grounding for agent runs."""

from __future__ import annotations

import json
from typing import Any

from ....config.models import ThinkingDepth
from ....context.window_budget import estimate_context_tokens
from ....llm.streaming_events import stream_scope
from magi.control.run_control import RunControl
from ..context_fingerprint import stable_hash
from ..contracts import AgentRunEventType
from ..model_capabilities import ModelCapabilityProfile
from .run_input import AgentRunRequest
from .run_journal import FunctionCallingRunJournal
from .step_models import FunctionCallingStepState
from .types import ExecutionOutcome


class FunctionCallingModelCapabilityFlow:
    """Validate model support and convert images into sourced observations."""

    def __init__(self, host: Any, journal: FunctionCallingRunJournal) -> None:
        self._host = host
        self._journal = journal

    async def prepare(
        self,
        *,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
        control: RunControl,
        thinking_depth: ThinkingDepth,
    ) -> ExecutionOutcome | None:
        profile = run_input.model_capabilities or ModelCapabilityProfile.from_model_context(
            getattr(self._host, "_active_model_context", None)
        )
        required_tools = tuple(
            str(name).strip()
            for name in run_input.capability_resolution.get("required_tools", [])
            if str(name).strip()
        )
        if required_tools and not profile.supports_tool_calls:
            return _unsupported_outcome(state, "tool_calls_unsupported")

        issue = profile.validate_run(
            has_images=_messages_contain_images(state.messages),
            tool_count=len(state.selected_tool_names),
            schema_tokens=(estimate_context_tokens(state.tools) if state.tools else 0),
        )
        if issue is None:
            return None
        if issue != "attachment_observation_required":
            return _unsupported_outcome(state, issue)
        return await self._ground_attachments(
            state=state,
            run_input=run_input,
            control=control,
            thinking_depth=thinking_depth,
        )

    async def _ground_attachments(
        self,
        *,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
        control: RunControl,
        thinking_depth: ThinkingDepth,
    ) -> ExecutionOutcome | None:
        grounding_prompt = (
            f"{state.effective_system_prompt}\n\n"
            "Attachment grounding step: inspect only the attached images. Return a compact "
            "JSON object with keys summary, visible_facts, uncertainty, and attachment_refs. "
            "Do not solve the broader task and do not expose hidden reasoning."
        )
        await self._journal.record_effective_context(
            state,
            mode="attachment_grounding",
            step_index=state.iteration,
            system_prompt=grounding_prompt,
            messages=state.messages,
            tools=[],
        )
        try:
            async with stream_scope(None):
                response = await self._host._call_llm_without_tools(
                    system_prompt=grounding_prompt,
                    messages=state.messages,
                    thinking_depth=thinking_depth,
                    json_mode=True,
                    timeout_seconds=run_input.llm_timeout_seconds,
                    session_id=run_input.session_id,
                    turn_id=run_input.turn_id,
                    execution_preset=run_input.execution_preset,
                    execution_agent_id=run_input.execution_agent_id,
                    iteration=0,
                    control=control,
                )
        except Exception as exc:
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason="attachment_observation_failed",
                error_text=self._host._format_exception_trace_text(exc),
                iterations=state.iteration,
            )

        observation = _normalize_attachment_observation(response.get("content"))
        state.messages = _strip_image_blocks(state.messages)
        state.messages.append(
            {
                "role": "user",
                "content": (
                    "[Runtime attachment observation]\n"
                    f"{json.dumps(observation, ensure_ascii=False, sort_keys=True)}\n"
                    "Use this sourced observation in place of the raw images for subsequent "
                    "tool steps."
                ),
            }
        )
        self._host._current_messages = state.messages
        if state.journal is not None:
            await state.journal.append(
                AgentRunEventType.ATTACHMENT_OBSERVED,
                step_index=0,
                payload={
                    "observation_hash": stable_hash(observation),
                    "observation_size_bytes": len(
                        json.dumps(observation, ensure_ascii=False, default=str).encode("utf-8")
                    ),
                },
            )
        return None


def _unsupported_outcome(
    state: FunctionCallingStepState,
    reason_code: str,
) -> ExecutionOutcome:
    return ExecutionOutcome(
        status="suspended" if reason_code == "attachments_unsupported" else "failed",
        content="",
        failure_reason=reason_code,
        error_text=_model_capability_error(reason_code),
        iterations=state.iteration,
    )


def _messages_contain_images(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        if any(
            isinstance(block, dict)
            and str(block.get("type") or "") in {"image", "image_url", "input_image"}
            for block in content
        ):
            return True
    return False


def _strip_image_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for message in messages:
        cloned = dict(message)
        content = cloned.get("content")
        if isinstance(content, list):
            cloned["content"] = [
                dict(block) if isinstance(block, dict) else block
                for block in content
                if not (
                    isinstance(block, dict)
                    and str(block.get("type") or "") in {"image", "image_url", "input_image"}
                )
            ]
        stripped.append(cloned)
    return stripped


def _normalize_attachment_observation(content: Any) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {
            "summary": "The model returned no attachment observation.",
            "visible_facts": [],
            "uncertainty": ["empty_model_observation"],
            "attachment_refs": [],
        }
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = {"summary": text}
    if not isinstance(decoded, dict):
        decoded = {"summary": text}
    return {
        "summary": str(decoded.get("summary") or "").strip(),
        "visible_facts": list(decoded.get("visible_facts") or []),
        "uncertainty": list(decoded.get("uncertainty") or []),
        "attachment_refs": list(decoded.get("attachment_refs") or []),
    }


def _model_capability_error(reason_code: str) -> str:
    return {
        "attachments_unsupported": (
            "The selected model cannot inspect the attached images. Choose a vision-capable "
            "model or remove the attachments."
        ),
        "tool_calls_unsupported": (
            "The selected model cannot execute the capabilities required by this run."
        ),
        "tool_schema_limit_exceeded": (
            "The initial capability set exceeds the selected model's tool-schema limit."
        ),
        "tool_schema_token_limit_exceeded": (
            "The initial capability schemas exceed the selected model's schema-token limit."
        ),
    }.get(reason_code, "The selected model does not support this run shape.")


__all__ = ["FunctionCallingModelCapabilityFlow"]
