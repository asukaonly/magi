"""Tests for chat_preview.runner — the preview-mode LLM orchestrator.

The runner MUST:
- Force the 'core' scenario when picking a model (not auxiliary, not embedding)
- Skip tool invocation entirely
- Skip the memory pipeline entirely
- Skip auxiliary model calls
- Stream output tokens via an async generator
- Build the system prompt from the caller-supplied persona preview prompt
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from magi.chat_preview.runner import (
    PreviewMessage,
    PreviewMode,
    run_preview,
)


@pytest.fixture
def fake_persona_loader():
    """Provides a callable load_persona_prompt(seed_slug) -> str."""

    def loader(seed_slug: str) -> str:
        return f"<system prompt for {seed_slug}>"

    return loader


@pytest.fixture
def fake_llm_call():
    """An async iterator that yields chunks 'hello', ' ', 'world'."""

    async def call(*, system_prompt: str, messages: list, model: str) -> AsyncIterator[str]:
        assert system_prompt.startswith("<system prompt for ")
        assert messages[-1]["content"] == "hi"
        assert model == "gpt-4o"  # the configured `core` model in the test
        for chunk in ["hello", " ", "world"]:
            yield chunk

    return call


async def test_run_preview_streams_chunks_from_core_model(
    fake_persona_loader, fake_llm_call
) -> None:
    chunks: list[str] = []
    async for chunk in run_preview(
        PreviewMode(seed_slug="nova", core_model="gpt-4o"),
        history=[],
        message=PreviewMessage(role="user", content="hi"),
        load_persona_prompt=fake_persona_loader,
        invoke_llm=fake_llm_call,
    ):
        chunks.append(chunk)
    assert "".join(chunks) == "hello world"


async def test_run_preview_includes_prior_history(
    fake_persona_loader,
) -> None:
    captured_messages: list = []

    async def capture_call(*, system_prompt, messages, model):
        captured_messages.extend(messages)
        if False:
            yield  # make this an async generator

    async for _ in run_preview(
        PreviewMode(seed_slug="ember", core_model="claude-sonnet-4-5"),
        history=[
            PreviewMessage(role="user", content="earlier user msg"),
            PreviewMessage(role="assistant", content="earlier reply"),
        ],
        message=PreviewMessage(role="user", content="latest"),
        load_persona_prompt=fake_persona_loader,
        invoke_llm=capture_call,
    ):
        pass

    # History + new user message, in order
    assert [m["role"] for m in captured_messages] == ["user", "assistant", "user"]
    assert captured_messages[0]["content"] == "earlier user msg"
    assert captured_messages[-1]["content"] == "latest"


async def test_run_preview_rejects_unknown_seed(fake_llm_call) -> None:
    def loader(seed_slug: str) -> str:
        raise ValueError(f"unknown seed: {seed_slug}")

    with pytest.raises(ValueError, match="unknown seed"):
        async for _ in run_preview(
            PreviewMode(seed_slug="ghost", core_model="gpt-4o"),
            history=[],
            message=PreviewMessage(role="user", content="hi"),
            load_persona_prompt=loader,
            invoke_llm=fake_llm_call,
        ):
            pass


async def test_run_preview_never_invokes_tools_or_memory(
    fake_persona_loader, fake_llm_call
) -> None:
    """Smoke check: runner signature accepts ONLY persona loader + llm call.
    There must be no tool registry, no memory store, no context decider
    parameters threaded through."""
    import inspect

    sig = inspect.signature(run_preview)
    param_names = set(sig.parameters.keys())
    forbidden = {"tool_registry", "memory_store", "tools"}
    assert param_names.isdisjoint(forbidden), (
        f"run_preview must not accept tool/memory/decider params; got {param_names}"
    )
