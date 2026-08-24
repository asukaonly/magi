"""Ring-2 service protocols for the unified run-loop handler.

The generic execution handler drives the agent loop without owning chat-domain
behavior. It receives collaborators through ``ChatHandlerDependencies`` and
only touches the small surface declared here.

These ``Protocol`` definitions pin exactly that surface so the dependency
bundle can be typed against ring-2 abstractions instead of the concrete chat
service classes. Inverting the typing here means a later task can relocate the
concrete services into the ``chat`` layer without creating new ``agent -> chat``
import edges through the bundle.

This module is a deliberate leaf: only stdlib / typing imports run at import
time. Parameter and return types that live in higher rings are referenced under
``TYPE_CHECKING`` with string annotations so importing the protocols never pulls
in chat (or any heavier) modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

if TYPE_CHECKING:
    from magi.config.models import ThinkingDepth
    from magi.control.run_control import RunControl
    from magi.llm.streaming_events import LLMStreamEvent

    from ..handlers.contracts import ChatReplyContext


@runtime_checkable
class PromptServiceProtocol(Protocol):
    """The exact prompt-service surface the generic handlers call.

    ``ChatPromptService`` matches this signature structurally. These methods are
    the complete surface used by the unified handler.
    """

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        thinking_depth: "ThinkingDepth | None" = None,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        llm_trace_callback=None,
        event_context: dict[str, Any] | None = None,
        control: "RunControl | None" = None,
    ) -> str:
        ...

    def call_llm_stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        thinking_depth: "ThinkingDepth | None" = None,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        event_context: dict[str, Any] | None = None,
        control: "RunControl | None" = None,
    ) -> "AsyncIterator[LLMStreamEvent]":
        ...

    def augment_system_prompt_with_reply_context(
        self,
        *,
        system_prompt: str,
        reply_context: "ChatReplyContext | None",
        recent_tool_state: list[dict[str, Any]] | None = None,
    ) -> str:
        ...

@runtime_checkable
class HistoryServiceProtocol(Protocol):
    """The exact history-service surface the generic handlers call.

    ``ChatContextAssembler`` matches this signature structurally.
    """

    def append_user_message(self, history_key: str, user_message: str) -> None:
        ...


__all__ = [
    "PromptServiceProtocol",
    "HistoryServiceProtocol",
]
