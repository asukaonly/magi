"""
Postprocessing helpers for function-calling loop.

This module keeps tool-result context shaping out of executor orchestration logic.
"""
from __future__ import annotations

import json
from typing import Any, Dict, cast

from ...asset_refs import normalize_asset_ref_list, normalize_asset_ref_payload
from ....memory.tool_context_formatter import compact_memory_tool_data
from ..tool_context_formatters import (
    ToolContextFormatterRegistry,
)


class FunctionCallingPostprocessor:
    """Build compact tool payloads for function-calling contexts."""

    def __init__(
        self,
        max_items: int = 40,
        max_text_chars: int = 2000,
        max_payload_chars: int = 24_000,
        formatter_registry: ToolContextFormatterRegistry | None = None,
    ) -> None:
        self.max_items = max_items
        self.max_text_chars = max_text_chars
        self.max_payload_chars = max(512, max_payload_chars)
        self._formatter_registry = formatter_registry or ToolContextFormatterRegistry.build_default(
            max_items=max_items,
            max_text_chars=max_text_chars,
            memory_formatter=self._compact_memory_query_data,
        )

    def build_tool_message_payload(self, tool_name: str, result: Any) -> Dict[str, Any]:
        """Build compact tool result payload for the next LLM turn."""
        error_code = getattr(result, "error_code", None)
        payload = {
            "success": bool(getattr(result, "success", False)),
            "data": self._compact_tool_data_for_context(
                tool_name=tool_name, data=getattr(result, "data", None)
            ),
            "error": self._bound_context_text(getattr(result, "error", None)),
            "error_code": error_code,
        }
        if tool_name == "memory_query":
            payload["context_role"] = "historical_recall_result"
        if error_code == "AMBIGUOUS_SCOPE":
            payload["recovery_guidance"] = (
                "The previous scan was blocked because the target location is ambiguous outside the current workspace. "
                "Ask the user for an explicit path or use web-search before attempting another external local scan."
            )
        return self._enforce_total_payload_limit(payload)

    def _compact_tool_data_for_context(self, tool_name: str, data: Any) -> Any:
        """Trim large tool payloads before injecting back into model context."""
        if isinstance(data, dict):
            compactor = self._formatter_registry.get(tool_name)
            if compactor is not None:
                return self._sanitize_structured_tool_data(compactor(data))
            data = self._sanitize_structured_tool_data(data)

        compacted, _ = self._compact_generic_value(data)
        return compacted

    def _compact_generic_value(
        self,
        value: Any,
        *,
        depth: int = 0,
        max_items: int | None = None,
        max_text_chars: int | None = None,
        max_depth: int = 8,
    ) -> tuple[Any, bool]:
        """Bound unregistered tool output without relying on tool-specific schemas."""
        item_limit = self.max_items if max_items is None else max(1, max_items)
        text_limit = self.max_text_chars if max_text_chars is None else max(1, max_text_chars)
        if depth >= max_depth:
            return "...[truncated]", True
        if isinstance(value, str):
            if len(value) <= text_limit:
                return value, False
            return value[:text_limit].rstrip() + "...[truncated]", True
        if isinstance(value, list):
            selected = value[:item_limit]
            compacted_items: list[Any] = []
            truncated = len(selected) < len(value)
            for item in selected:
                compacted, item_truncated = self._compact_generic_value(
                    item,
                    depth=depth + 1,
                    max_items=item_limit,
                    max_text_chars=text_limit,
                    max_depth=max_depth,
                )
                compacted_items.append(compacted)
                truncated = truncated or item_truncated
            return compacted_items, truncated
        if isinstance(value, dict):
            selected_items = list(value.items())[:item_limit]
            compacted_dict: dict[str, Any] = {}
            truncated = len(selected_items) < len(value)
            for key, item in selected_items:
                compacted, item_truncated = self._compact_generic_value(
                    item,
                    depth=depth + 1,
                    max_items=item_limit,
                    max_text_chars=text_limit,
                    max_depth=max_depth,
                )
                compacted_dict[str(key)] = compacted
                truncated = truncated or item_truncated
            if truncated:
                compacted_dict["__context_truncated__"] = True
            return compacted_dict, truncated
        return value, False

    def _bound_context_text(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text_limit = min(
            self.max_text_chars,
            max(64, self.max_payload_chars // 4),
        )
        if len(value) <= text_limit:
            return value
        return value[:text_limit].rstrip() + "...[truncated]"

    def _enforce_total_payload_limit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._serialized_length(payload) <= self.max_payload_chars:
            return payload

        source_data = payload.get("data")
        stages = (
            (20, 1_000, 7),
            (10, 500, 6),
            (5, 240, 5),
            (2, 120, 4),
            (1, 80, 3),
        )
        for item_limit, text_limit, depth_limit in stages:
            compacted_data, _ = self._compact_generic_value(
                source_data,
                max_items=min(self.max_items, item_limit),
                max_text_chars=min(self.max_text_chars, text_limit),
                max_depth=depth_limit,
            )
            candidate = dict(payload)
            candidate["data"] = compacted_data
            if self._serialized_length(candidate) <= self.max_payload_chars:
                return candidate

        fallback = dict(payload)
        fallback["data"] = {"__context_truncated__": True}
        if self._serialized_length(fallback) <= self.max_payload_chars:
            return fallback

        fallback.pop("recovery_guidance", None)
        fallback["error"] = self._truncate_to_length(fallback.get("error"), 64)
        return fallback

    def compact_tool_message_content(self, content: Any) -> tuple[Any, bool]:
        """Bound an existing tool message before it is reused in a model request."""
        if not isinstance(content, str) or len(content) <= self.max_payload_chars:
            return content, False
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return self._truncate_to_length(content, self.max_payload_chars), True

        if isinstance(payload, dict):
            if "error" in payload:
                payload["error"] = self._bound_context_text(payload.get("error"))
            compacted = self._enforce_total_payload_limit(payload)
        else:
            compacted, _ = self._compact_generic_value(
                payload,
                max_items=2,
                max_text_chars=120,
                max_depth=4,
            )
        rendered = json.dumps(compacted, ensure_ascii=False)
        if len(rendered) > self.max_payload_chars:
            rendered = json.dumps({"__context_truncated__": True}, ensure_ascii=False)
        return rendered, rendered != content

    @staticmethod
    def _serialized_length(value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False, default=str))

    @staticmethod
    def _truncate_to_length(value: Any, max_chars: int) -> Any:
        if not isinstance(value, str) or len(value) <= max_chars:
            return value
        marker = "...[truncated]"
        keep = max(0, max_chars - len(marker))
        return value[:keep].rstrip() + marker

    def _sanitize_structured_tool_data(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        sanitized = normalize_asset_ref_payload(data)
        for key in ("attachments", "chat_attachments"):
            value = sanitized.get(key)
            if isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_attachment_item(item)
                    for item in value
                    if isinstance(item, dict)
                ]

        asset_refs = sanitized.get("asset_refs")
        if isinstance(asset_refs, list):
            sanitized["asset_refs"] = [
                self._sanitize_asset_ref_item(item)
                for item in normalize_asset_ref_list(asset_refs)
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
    def _sanitize_asset_ref_item(item: Dict[str, Any]) -> Dict[str, Any]:
        allowed_keys = (
            "asset_ref_id",
            "attachment_id",
            "event_id",
            "source_type",
            "source_item_id",
            "original_name",
            "display_name",
            "capture_time",
            "captured_at",
            "occurred_at",
            "kind",
            "resolver_tool",
            "resolution_state",
        )
        sanitized = {
            key: item[key]
            for key in allowed_keys
            if key in item and item[key] is not None
        }
        attributes = item.get("attributes")
        if isinstance(attributes, dict) and attributes:
            sanitized["attributes"] = dict(attributes)
        return sanitized

    def _compact_memory_query_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return cast(
            Dict[str, Any],
            compact_memory_tool_data(
                data,
                max_items=self.max_items,
                max_text_chars=self.max_text_chars,
            ),
        )
