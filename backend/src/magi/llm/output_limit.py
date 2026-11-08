"""Explicit failure for a generation stopped at its output-token limit."""

from __future__ import annotations

from typing import Any


class OutputLimitReached(RuntimeError):
    """Keep token usage available while rejecting incomplete text and tool calls."""

    def __init__(self, usage: Any = None, *, usage_format: str = "normalized") -> None:
        self.usage = usage
        self.usage_format = usage_format
        super().__init__("Model generation reached its output-token limit before completion")

    def token_count(self, name: str) -> int:
        value = self.usage.get(name) if isinstance(self.usage, dict) else getattr(self.usage, name, None)
        return value if isinstance(value, int) and value > 0 else 0
