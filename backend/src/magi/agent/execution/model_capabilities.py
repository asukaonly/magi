"""Stable provider capability contract used before a unified agent run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelCapabilityProfile:
    """Model features that affect message/tool assembly, not task semantics."""

    supports_images: bool = False
    supports_tool_calls: bool = True
    supports_images_with_tools: bool = False
    supports_parallel_tools: bool = False
    max_tool_schemas: int | None = None
    max_schema_tokens: int | None = None

    @classmethod
    def from_model_context(cls, context: Any) -> "ModelCapabilityProfile":
        """Project the active model context into the runtime contract."""

        return cls(
            supports_images=bool(getattr(context, "supports_images", False)),
            supports_tool_calls=bool(getattr(context, "supports_tool_calls", True)),
            supports_images_with_tools=bool(
                getattr(context, "supports_images_with_tools", False)
            ),
            supports_parallel_tools=bool(
                getattr(context, "supports_parallel_tools", False)
            ),
            max_tool_schemas=_positive_int_or_none(
                getattr(context, "max_tool_schemas", None)
            ),
            max_schema_tokens=_positive_int_or_none(
                getattr(context, "max_schema_tokens", None)
            ),
        )

    def validate_run(
        self,
        *,
        has_images: bool,
        tool_count: int,
        schema_tokens: int = 0,
    ) -> str | None:
        if has_images and not self.supports_images:
            return "attachments_unsupported"
        if tool_count and not self.supports_tool_calls:
            return "tool_calls_unsupported"
        if has_images and tool_count and not self.supports_images_with_tools:
            return "attachment_observation_required"
        if self.max_tool_schemas is not None and tool_count > self.max_tool_schemas:
            return "tool_schema_limit_exceeded"
        if self.max_schema_tokens is not None and schema_tokens > self.max_schema_tokens:
            return "tool_schema_token_limit_exceeded"
        return None


def _positive_int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


__all__ = ["ModelCapabilityProfile"]
