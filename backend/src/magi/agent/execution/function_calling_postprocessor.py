"""
Postprocessing helpers for function-calling loop.

This module keeps tool-result context shaping out of executor orchestration logic.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from ...memory.tool_context_formatter import compact_memory_tool_data
from .tool_context_formatters import (
    compact_agent_tool_data,
    compact_bash_tool_data,
    compact_file_read_tool_data,
    compact_glob_tool_data,
    compact_grep_tool_data,
)


class FunctionCallingPostprocessor:
    """Build compact tool payloads for function-calling contexts."""

    def __init__(
        self,
        max_items: int = 40,
        max_text_chars: int = 2000,
    ) -> None:
        self.max_items = max_items
        self.max_text_chars = max_text_chars
        self._tool_compactors: dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "glob": self._compact_glob_data,
            "bash": self._compact_bash_data,
            "grep": self._compact_grep_data,
            "file_read": self._compact_file_read_data,
            "agent": self._compact_agent_data,
            "memory_query": self._compact_memory_query_data,
        }

    def build_tool_message_payload(self, tool_name: str, result: Any) -> Dict[str, Any]:
        """Build compact tool result payload for the next LLM turn."""
        payload = {
            "success": bool(getattr(result, "success", False)),
            "data": self._compact_tool_data_for_context(
                tool_name=tool_name, data=getattr(result, "data", None)
            ),
            "error": getattr(result, "error", None),
        }
        if tool_name == "memory_query":
            payload.update(
                {
                    "source_of_truth_for_turn": True,
                    "context_role": "historical_recall_result",
                    "usage_guidance": (
                        "Treat memory_query results as the source of truth for historical recall in this turn. "
                        "Do not replace missing recall results with implicit memory or guesses."
                    ),
                }
            )
        return payload

    def _compact_tool_data_for_context(self, tool_name: str, data: Any) -> Any:
        """Trim large tool payloads before injecting back into model context."""
        if not isinstance(data, dict):
            return data

        compactor = self._tool_compactors.get(tool_name)
        if compactor is not None:
            return compactor(data)

        return data

    def _compact_memory_query_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_memory_tool_data(
            data,
            max_items=self.max_items,
            max_text_chars=self.max_text_chars,
        )

    def _compact_glob_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_glob_tool_data(data, max_items=self.max_items)

    def _compact_bash_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_bash_tool_data(data, max_text_chars=self.max_text_chars)

    def _compact_grep_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_grep_tool_data(data, max_items=self.max_items)

    def _compact_file_read_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_file_read_tool_data(data, max_text_chars=self.max_text_chars)

    def _compact_agent_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_agent_tool_data(data, max_items=self.max_items)
