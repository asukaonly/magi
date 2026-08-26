"""Persona preview chat orchestrator.

The single public function is ``run_preview``. It must:
- Force the `core` scenario model (caller supplies the model id explicitly)
- Skip tool invocation entirely
- Receive already-rendered stable and dynamic prompt layers
- Stream output tokens via an async generator

Dependencies are injected (persona loader + llm caller) so unit tests don't
need the real persona registry or LLM provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Protocol

from magi.utils.model_context_messages import (
    build_runtime_world_state_message,
    build_working_context_message,
)


@dataclass(frozen=True)
class PreviewMode:
    """The persona + model choice for a single preview run."""

    seed_slug: str
    core_model: str


@dataclass(frozen=True)
class PreviewMessage:
    """A single turn in the preview transcript."""

    role: str  # "user" | "assistant"
    content: str


class _LLMCall(Protocol):
    """The shape ``invoke_llm`` must satisfy."""

    def __call__(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        model: str,
    ) -> AsyncIterator[str]: ...


async def run_preview(
    mode: PreviewMode,
    *,
    history: Iterable[PreviewMessage],
    message: PreviewMessage,
    system_prompt: str,
    runtime_world_state: str,
    working_context: str,
    invoke_llm: _LLMCall,
) -> AsyncIterator[str]:
    """Stream the persona's reply to ``message`` given the prior ``history``."""

    wire_messages: list[dict] = [
        {"role": m.role, "content": m.content} for m in history
    ]
    runtime_message = build_runtime_world_state_message(runtime_world_state)
    working_message = build_working_context_message(working_context)
    if runtime_message is not None:
        wire_messages.append(runtime_message)
    if working_message is not None:
        wire_messages.append(working_message)
    wire_messages.append({"role": message.role, "content": message.content})

    async for chunk in invoke_llm(
        system_prompt=system_prompt,
        messages=wire_messages,
        model=mode.core_model,
    ):
        yield chunk
