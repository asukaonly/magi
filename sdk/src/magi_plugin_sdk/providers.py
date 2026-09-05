"""Wire-safe requests, results and bounded events for replaceable providers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol

from pydantic import Field, JsonValue

from .runtime import InvocationIdentity, RuntimeModel


class ProviderUsage(RuntimeModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ProviderToolCall(RuntimeModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ModelRequest(RuntimeModel):
    identity: InvocationIdentity
    model: str = Field(min_length=1, max_length=256)
    messages: list[dict[str, JsonValue]] = Field(max_length=10000)
    tools: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=256)
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float = Field(default=0.7, ge=0, le=2)
    options: dict[str, JsonValue] = Field(default_factory=dict)


class ModelResult(RuntimeModel):
    content: str = ""
    tool_calls: list[ProviderToolCall] = Field(default_factory=list, max_length=256)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    finish_reason: str | None = None


class ModelEvent(RuntimeModel):
    kind: Literal["text", "reasoning", "tool_call", "completed"]
    delta: str = Field(default="", max_length=65536)
    tool_call: ProviderToolCall | None = None
    result: ModelResult | None = None


class ExternalAgentRequest(RuntimeModel):
    identity: InvocationIdentity
    prompt: str
    workspace: str
    files_hint: list[str] = Field(default_factory=list)
    constraints: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=600, gt=0, le=3600)
    model: str | None = None


class ExternalAgentResult(RuntimeModel):
    status: Literal["succeeded", "failed", "cancelled", "uncertain"]
    summary: str = ""
    exit_code: int = 0
    error: str | None = None
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    cost_usd: float | None = Field(default=None, ge=0)


class ExternalAgentEvent(RuntimeModel):
    kind: Literal[
        "stdout",
        "stderr",
        "tool_call",
        "tool_result",
        "assistant_text",
        "thinking",
        "status",
        "error",
        "completed",
    ]
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    result: ExternalAgentResult | None = None


class ModelProvider(Protocol):
    async def invoke(self, request: ModelRequest) -> ModelResult: ...
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...


class ExternalAgentProvider(Protocol):
    async def invoke(self, request: ExternalAgentRequest) -> ExternalAgentResult: ...
    def stream(
        self, request: ExternalAgentRequest
    ) -> AsyncIterator[ExternalAgentEvent]: ...


__all__ = [
    "ProviderUsage",
    "ProviderToolCall",
    "ModelRequest",
    "ModelResult",
    "ModelEvent",
    "ExternalAgentRequest",
    "ExternalAgentResult",
    "ExternalAgentEvent",
    "ModelProvider",
    "ExternalAgentProvider",
]
