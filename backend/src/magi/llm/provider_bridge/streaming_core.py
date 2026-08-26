"""Shared streaming helpers and host protocols for provider bridge mixins."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Dict, Protocol

from ...config.models import ThinkingDepth


class ThinkTagScrubber:
    """Strip ``<think>...</think>`` blocks from streaming text content."""

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self._inside = False
        self._pending = ""

    def feed(self, chunk: str) -> tuple[str, str]:
        """Process ``chunk`` and return ``(visible_text, reasoning_text)``."""
        if not chunk:
            return "", ""
        text = self._pending + chunk
        self._pending = ""
        visible: list[str] = []
        reasoning: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if self._inside:
                close_idx = text.find(self.CLOSE, i)
                if close_idx == -1:
                    tail = len(self.CLOSE) - 1
                    if n - i <= tail:
                        self._pending = text[i:]
                        i = n
                    else:
                        safe_end = n - tail
                        reasoning.append(text[i:safe_end])
                        self._pending = text[safe_end:]
                        i = n
                    break
                if close_idx > i:
                    reasoning.append(text[i:close_idx])
                i = close_idx + len(self.CLOSE)
                self._inside = False
            else:
                open_idx = text.find(self.OPEN, i)
                if open_idx == -1:
                    tail = len(self.OPEN) - 1
                    if n - i <= tail:
                        self._pending = text[i:]
                        i = n
                    else:
                        safe_end = n - tail
                        visible.append(text[i:safe_end])
                        self._pending = text[safe_end:]
                        i = n
                    break
                if open_idx > i:
                    visible.append(text[i:open_idx])
                i = open_idx + len(self.OPEN)
                self._inside = True
        return "".join(visible), "".join(reasoning)

    def flush(self) -> tuple[str, str]:
        """Return any leftover buffered text when the stream ends."""
        if not self._pending:
            return "", ""
        leftover = self._pending
        self._pending = ""
        if self._inside:
            return "", leftover
        return leftover, ""


class ProviderBridgeStreamingHostProtocol(Protocol):
    llm: Any

    def is_anthropic(self) -> bool: ...

    def _convert_messages_to_anthropic(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def _convert_messages_to_openai(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]: ...

    def _cache_marked_system(self, system_prompt: str, *, cache_whole: bool = False) -> Any: ...

    def _mark_message_cache_breakpoints(
        self,
        injected_messages: list[dict[str, Any]],
        api_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...

    def _apply_cache_routing(
        self, kwargs: dict[str, Any], event_context: dict[str, Any] | None
    ) -> dict[str, Any]: ...

    def _with_cache_observation(
        self,
        event_context: dict[str, Any] | None,
        *,
        system_prompt: str,
        tools: list[dict[str, Any]] | None,
        messages: list[dict[str, Any]] | None = None,
        cache_whole_system: bool = False,
    ) -> dict[str, Any] | None: ...

    def _anthropic_usage_to_wire(self, usage_data: Any) -> dict[str, int] | None: ...

    def _openai_usage_to_wire(self, usage_data: Any) -> dict[str, int] | None: ...

    def _extract_anthropic_stream_usage(self, stream: Any, usage_data: Any) -> Any: ...

    def _extract_openai_stream_usage(self, usage_data: Any) -> Any: ...

    async def _emit_usage_event(
        self,
        *,
        success: bool,
        latency_ms: int,
        usage: Any,
        event_context: dict[str, Any] | None,
        error: str | None = None,
    ) -> None: ...

    def _resolve_chat_concurrency_limit(self) -> int: ...

    def _limit_concurrency(
        self,
        *,
        request_family: str,
        limit: int | None = None,
        priority: Any = None,
    ) -> AbstractAsyncContextManager[None]: ...


__all__ = ["ProviderBridgeStreamingHostProtocol", "ThinkTagScrubber"]
