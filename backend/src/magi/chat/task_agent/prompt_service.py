"""Prompt helpers used by the unified chat agent loop."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from magi.agent.task_agents.common import TaskAgentLLMService
from magi.agent.task_agents.handlers.contracts import ChatReplyContext
from magi.config.models import LLMScenario, ThinkingDepth
from magi.control.run_control import RunControl
from magi.llm.streaming_events import LLMStreamEvent


class ChatPromptService:
    """Own direct LLM invocation and turn-local prompt augmentation."""

    def __init__(self, *, llm_adapter=None, llm_pool=None) -> None:
        self._llm = llm_adapter
        self._llm_pool = llm_pool
        self._llm_service = TaskAgentLLMService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            scenario=LLMScenario.CORE,
            logger_name="chat",
        )

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        thinking_depth: ThinkingDepth | None = None,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        llm_trace_callback=None,
        event_context: dict[str, Any] | None = None,
        control: RunControl | None = None,
    ) -> str:
        return await self._llm_service.call(
            system_prompt=system_prompt,
            messages=messages,
            disable_thinking=disable_thinking,
            thinking_depth=thinking_depth,
            temperature=0.7,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            llm_trace_callback=llm_trace_callback,
            event_context=event_context,
            control=control,
        )

    async def call_llm_stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        thinking_depth: ThinkingDepth | None = None,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        event_context: dict[str, Any] | None = None,
        control: RunControl | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        async for event in self._llm_service.call_stream(
            system_prompt=system_prompt,
            messages=messages,
            disable_thinking=disable_thinking,
            thinking_depth=thinking_depth,
            temperature=0.7,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
            control=control,
        ):
            yield event

    def augment_system_prompt_with_reply_context(
        self,
        *,
        system_prompt: str,
        reply_context: ChatReplyContext | None,
        recent_tool_state: list[dict[str, Any]] | None = None,
    ) -> str:
        blocks = [
            block
            for block in (
                self.build_recent_tool_state_block(recent_tool_state),
                self.build_reply_context_block(reply_context),
            )
            if block
        ]
        return "\n\n".join([system_prompt, *blocks])

    def build_recent_tool_state_block(
        self,
        recent_tool_state: list[dict[str, Any]] | None,
    ) -> str:
        items = recent_tool_state if isinstance(recent_tool_state, list) else []
        lines: list[str] = []
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name") or "unknown")
            status = str(item.get("status") or "unknown")
            line = f"- {tool_name}: {status}"
            execution_time_ms = item.get("execution_time_ms")
            if execution_time_ms not in (None, ""):
                line += f" | duration_ms={execution_time_ms}"
            outcome = str(item.get("outcome") or "").strip()
            if outcome:
                line += f" | outcome={outcome}"
            handles = item.get("handles")
            if isinstance(handles, list) and handles:
                line += f" | handles={', '.join(str(handle) for handle in handles[:4])}"
            error_code = str(item.get("error_code") or "").strip()
            if error_code:
                line += f" | error_code={error_code}"
            lines.append(line)
        if not lines:
            return ""
        return "\n".join(
            [
                "# Recent Tool State",
                "Use this only as lightweight continuity. Call `trace_query` for exact parameters, durations, or full outputs.",
                *lines,
            ]
        )

    def build_reply_context_block(self, reply_context: ChatReplyContext | None) -> str:
        if reply_context is None:
            return ""
        lines = [
            (
                "Current message is replying to:"
                if reply_context.is_explicit_reply
                else "Most recent assistant turn includes reusable context:"
            ),
            f"- speaker: {reply_context.role}",
            f'- message: "{reply_context.content_excerpt}"',
        ]
        if reply_context.structured_payload:
            lines.extend(
                [
                    "- reusable reply data:",
                    json.dumps(reply_context.structured_payload, ensure_ascii=False),
                ]
            )
            if reply_context.structured_payload.get("asset_refs"):
                lines.append(
                    "- asset workflow note: "
                    + self._build_asset_workflow_note(
                        reply_context.structured_payload.get("asset_refs")
                    )
                )
        if reply_context.references_prior_turn:
            lines.append(
                "- note: this reply points to an earlier turn, so keep that thread continuity explicit."
            )
        return "\n".join(lines)

    @staticmethod
    def _build_asset_workflow_note(asset_refs: Any) -> str:
        items = asset_refs if isinstance(asset_refs, list) else []
        resolver_tools = sorted(
            {
                str(item.get("resolver_tool") or "").strip()
                for item in items
                if isinstance(item, dict)
                and str(item.get("resolver_tool") or "").strip()
            }
        )
        if resolver_tools:
            tools_text = ", ".join(f"`{tool_name}`" for tool_name in resolver_tools)
            return (
                "call the stored asset resolver tool(s) "
                f"{tools_text} to obtain file paths, then prepare chat attachments."
            )
        return (
            "call the appropriate source resolver to obtain file paths, "
            "then prepare chat attachments."
        )


__all__ = ["ChatPromptService"]
