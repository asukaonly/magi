"""Message history compaction helpers for function-calling execution."""

from __future__ import annotations

import json
from typing import Any

from .types import ToolMessageBlock


class FunctionCallingMessageHistoryMixin:
    """Compact older tool-call protocol blocks without breaking message order."""

    _RAW_TOOL_HISTORY_LIMIT: int
    _COMPACT_TRIGGER: int

    def _append_message(self, messages: list[dict[str, Any]], message: dict[str, Any]) -> None:
        """Append a message and compact old tool interactions."""
        messages.append(message)
        if self._compact_message_history(messages):
            self._invalidate_recorded_context_usage()

    def _compact_message_history(self, messages: list[dict[str, Any]]) -> bool:
        """Keep only a few raw tool turns and report whether history changed."""
        completed_blocks = self._collect_completed_tool_blocks(messages)
        # Hysteresis: leave the history append-only (cache-preserving) until raw
        # tool blocks reach the high-water mark; then summarize down to the floor
        # in one batch (#100/P2b).
        if len(completed_blocks) < self._COMPACT_TRIGGER:
            return False

        blocks_to_summarize = completed_blocks[:-self._RAW_TOOL_HISTORY_LIMIT]
        summary_lines: list[str] = []
        for block in blocks_to_summarize:
            summary_lines.extend(self._build_block_summaries(block))

        if not summary_lines:
            return False

        drop_start = blocks_to_summarize[0].start
        drop_end = blocks_to_summarize[-1].end
        if drop_start > 0 and self._is_tool_summary_message(messages[drop_start - 1]):
            existing_summary = self._extract_summary_lines(messages[drop_start - 1])
            summary_lines = existing_summary + summary_lines
            drop_start -= 1

        summary_message = {
            "role": "assistant",
            "content": "Previous tool activity summary:\n" + "\n".join(summary_lines),
        }
        del messages[drop_start:drop_end]
        messages.insert(drop_start, summary_message)
        return True

    def _invalidate_recorded_context_usage(self) -> None:
        context_compactor = getattr(self, "_context_compactor", None)
        invalidate = getattr(context_compactor, "invalidate_recorded_usage", None)
        if callable(invalidate):
            invalidate()

    def _collect_completed_tool_blocks(self, messages: list[dict[str, Any]]) -> list[ToolMessageBlock]:
        """Collect protocol-complete assistant tool-call blocks from message history."""
        blocks: list[ToolMessageBlock] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.get("role") != "assistant" or not message.get("tool_calls"):
                index += 1
                continue

            tool_calls = message.get("tool_calls", [])
            expected_tool_messages = len(tool_calls) if isinstance(tool_calls, list) else 0
            if expected_tool_messages <= 0:
                index += 1
                continue

            tool_messages: list[dict[str, Any]] = []
            next_index = index + 1
            while next_index < len(messages) and messages[next_index].get("role") == "tool":
                tool_messages.append(messages[next_index])
                next_index += 1

            if len(tool_messages) < expected_tool_messages:
                break

            blocks.append(
                ToolMessageBlock(
                    start=index,
                    end=index + 1 + len(tool_messages),
                    assistant_message=message,
                    tool_messages=tool_messages[:expected_tool_messages],
                )
            )
            index = next_index

        return blocks

    def _build_block_summaries(self, block: ToolMessageBlock) -> list[str]:
        """Build deterministic summaries for one completed tool block."""
        tool_calls = block.assistant_message.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            tool_calls = []
        summaries: list[str] = []
        for call, tool_message in zip(tool_calls, block.tool_messages):
            tool_name = call.get("function", {}).get("name", "unknown")
            summaries.append(self._build_tool_summary(tool_name, tool_message, call))
        return summaries

    def _is_tool_summary_message(self, message: dict[str, Any]) -> bool:
        """Return True for synthetic tool-history summary assistant messages."""
        if message.get("role") != "assistant":
            return False
        content = str(message.get("content", "") or "")
        return content.startswith("Previous tool activity summary:\n")

    def _extract_summary_lines(self, message: dict[str, Any]) -> list[str]:
        """Extract bullet lines from an existing synthetic summary message."""
        content = str(message.get("content", "") or "")
        lines = content.splitlines()[1:]
        return [line for line in lines if line.strip()]

    def _build_tool_summary(
        self,
        tool_name: str,
        tool_message: dict[str, Any],
        call: dict[str, Any] | None = None,
    ) -> str:
        try:
            payload = json.loads(str(tool_message.get("content", "{}")))
        except json.JSONDecodeError:
            payload = {}
        success = bool(payload.get("success"))
        data = payload.get("data")
        error = payload.get("error")
        status = "ok" if success else "failed"
        detail = ""
        if isinstance(data, dict):
            result_preview = data.get("result_preview")
            if result_preview:
                detail = f" | {result_preview}"
            elif isinstance(data.get("worker_result"), dict):
                summary = str(data["worker_result"].get("summary", "")).strip()
                if summary:
                    detail = f" | {summary}"
            elif data.get("match_count") is not None:
                detail = f" | matches={data.get('match_count')}"
            elif data.get("return_code") is not None:
                detail = f" | return_code={data.get('return_code')}"
                stdout = str(data.get("stdout_preview") or data.get("stdout") or "").strip()
                if stdout:
                    stdout_short = stdout[:200].replace("\r\n", "\n").replace("\r", "\n")
                    detail += f"\n  stdout: {stdout_short}"
        if error and not success:
            detail = f" | error={error}"
        args_hint = ""
        if call and isinstance(call, dict):
            func = call.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            command = args.get("command") or args.get("query") or args.get("path")
            if command:
                args_hint = f" [{str(command)[:120]}]"
        return f"- {tool_name}{args_hint}: {status}{detail}"
