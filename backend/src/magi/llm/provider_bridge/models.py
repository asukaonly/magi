"""Normalized provider bridge response models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderToolCall:
    """Normalized tool call returned by a provider."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderUsage:
    """Normalized token usage returned by a provider."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Subset of cache_write_tokens written with a 1h TTL (Anthropic prices these
    # at 2x base input vs 1.25x for the 5m default). 0 for vendors/requests with
    # no 1h breakdown. See pricing.calculate_chat_cost.
    cache_write_1h_tokens: int = 0
    # Whether the provider usage payload exposed cache-specific fields at all.
    # This distinguishes "provider reported zero cache" from "provider did not
    # report cache fields", which is essential for cache diagnostics.
    cache_fields_seen: bool = False


@dataclass
class ProviderResponse:
    """Normalized response returned by a provider."""

    content: str = ""
    tool_calls: list[ProviderToolCall] | None = None
    assistant_message: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    usage: ProviderUsage | None = None

    def __post_init__(self) -> None:
        if self.tool_calls is None:
            self.tool_calls = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ToolStreamResult:
    """Result of a streaming tool-call LLM invocation."""

    provider_response: ProviderResponse
    text_chunks_emitted: int = 0
    has_tool_calls: bool = False
