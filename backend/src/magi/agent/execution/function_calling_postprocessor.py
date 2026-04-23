"""
Postprocessing helpers for function-calling loop.

This module keeps tool-result context shaping out of executor orchestration logic.
"""
from __future__ import annotations

from typing import Any, Dict

from ...memory.tool_context_formatter import compact_memory_tool_data
from .tool_context_formatters import (
    ToolContextFormatterRegistry,
)


class FunctionCallingPostprocessor:
    """Build compact tool payloads for function-calling contexts."""

    def __init__(
        self,
        max_items: int = 40,
        max_text_chars: int = 2000,
        formatter_registry: ToolContextFormatterRegistry | None = None,
    ) -> None:
        self.max_items = max_items
        self.max_text_chars = max_text_chars
        self._formatter_registry = formatter_registry or ToolContextFormatterRegistry.build_default(
            max_items=max_items,
            max_text_chars=max_text_chars,
            memory_formatter=self._compact_memory_query_data,
        )

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

        compactor = self._formatter_registry.get(tool_name)
        if compactor is not None:
            return self._sanitize_structured_tool_data(compactor(data))

        return self._sanitize_structured_tool_data(data)

    def _sanitize_structured_tool_data(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        sanitized = dict(data)
        for key in ("attachments", "chat_attachments"):
            value = sanitized.get(key)
            if isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_attachment_item(item)
                    for item in value
                    if isinstance(item, dict)
                ]

        for key in ("candidate_photo_refs", "photo_refs"):
            value = sanitized.get(key)
            if isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_photo_ref_item(item)
                    for item in value
                    if isinstance(item, dict)
                ]

        assistant_payload = sanitized.get("assistant_payload")
        if isinstance(assistant_payload, dict):
            sanitized["assistant_payload"] = self._sanitize_structured_tool_data(assistant_payload)
        return sanitized

    @staticmethod
    def _sanitize_attachment_item(item: Dict[str, Any]) -> Dict[str, Any]:
        allowed_keys = ("attachment_id", "kind", "original_name", "mime_type", "size_bytes")
        return {
            key: item[key]
            for key in allowed_keys
            if key in item and item[key] is not None
        }

    @staticmethod
    def _sanitize_photo_ref_item(item: Dict[str, Any]) -> Dict[str, Any]:
        allowed_keys = (
            "photo_ref_id",
            "attachment_id",
            "event_id",
            "source_item_id",
            "original_name",
            "capture_time",
            "captured_at",
            "kind",
        )
        return {
            key: item[key]
            for key in allowed_keys
            if key in item and item[key] is not None
        }

    def _compact_memory_query_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_memory_tool_data(
            data,
            max_items=self.max_items,
            max_text_chars=self.max_text_chars,
        )
