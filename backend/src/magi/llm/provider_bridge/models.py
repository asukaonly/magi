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
    # TTL-specific counts are subsets of cache_write_tokens, never extra input.
    cache_write_1h_tokens: int = 0
    cache_write_12h_tokens: int = 0
    service_tier: str | None = None
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
