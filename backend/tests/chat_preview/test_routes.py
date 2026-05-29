"""HTTP API contract tests for POST /api/chat/preview."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.chat_preview_routes import build_default_chat_preview_router


@pytest.fixture
def app_with_preview():
    async def fake_llm(*, system_prompt, messages, model):
        for chunk in ["hi", " ", "there"]:
            yield chunk

    def fake_loader(seed_slug: str) -> str:
        if seed_slug == "ghost":
            raise ValueError("unknown seed: ghost")
        return f"<system prompt for {seed_slug}>"

    # The LLM deps now receive the request's optional ``llm_override``; the
    # fakes ignore it but must accept the positional arg.
    def fake_core_model(llm_override=None) -> str:
        return "test-core-model"

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: fake_loader,
            llm_call_dep=lambda _override=None: fake_llm,
            core_model_dep=fake_core_model,
        ),
    )
    return app


def test_post_preview_returns_streamed_text(app_with_preview) -> None:
    client = TestClient(app_with_preview)
    with client.stream(
        "POST",
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": "hello"},
        },
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes())
    assert b"hi there" in body


def test_post_preview_validates_seed_slug(app_with_preview) -> None:
    client = TestClient(app_with_preview)
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "ghost",
            "history": [],
            "message": {"role": "user", "content": "hi"},
        },
    )
    assert response.status_code == 400
    assert "unknown seed" in response.text


def test_post_preview_rejects_empty_message(app_with_preview) -> None:
    client = TestClient(app_with_preview)
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": ""},
        },
    )
    assert response.status_code == 422  # Pydantic validation


def test_post_preview_caps_history_length(app_with_preview) -> None:
    """History longer than 20 turns is rejected to bound LLM cost per request."""
    client = TestClient(app_with_preview)
    too_long = [{"role": "user", "content": "x"}] * 21
    response = client.post(
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": too_long,
            "message": {"role": "user", "content": "hi"},
        },
    )
    assert response.status_code == 422


def test_post_preview_threads_llm_override_to_deps() -> None:
    """An unsaved ``llm_override`` from onboarding reaches both LLM deps."""
    seen: dict[str, object] = {}

    async def fake_llm(*, system_prompt, messages, model):
        yield "ok"

    def llm_call_dep(override=None):
        seen["llm_call_override"] = override
        return fake_llm

    def core_model_dep(override=None) -> str:
        seen["core_model_override"] = override
        return "override-core-model"

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: (lambda slug: f"<prompt {slug}>"),
            llm_call_dep=llm_call_dep,
            core_model_dep=core_model_dep,
        ),
    )

    override = {
        "providers": {
            "openai": {
                "enabled": True,
                "provider_type": "openai",
                "api_key": "sk-test",
            }
        },
        "selections": {
            "core": {"provider_id": "openai", "model": "gpt-4o"},
            "context_decider": {"provider_id": "openai", "model": "gpt-4o-mini"},
        },
    }
    client = TestClient(app)
    with client.stream(
        "POST",
        "/chat/preview",
        json={
            "seed_slug": "nova",
            "history": [],
            "message": {"role": "user", "content": "hi"},
            "llm_override": override,
        },
    ) as response:
        assert response.status_code == 200
        b"".join(response.iter_bytes())

    # Both deps received the parsed LLMSettings override (not None).
    assert seen["llm_call_override"] is not None
    assert seen["core_model_override"] is not None
    assert seen["core_model_override"].selections["core"].model == "gpt-4o"


def _capture_prompt_app(captured: dict) -> FastAPI:
    """Build a preview app whose fake LLM records the system prompt it gets."""

    async def fake_llm(*, system_prompt, messages, model):
        captured["system_prompt"] = system_prompt
        yield "ok"

    def fake_loader(seed_slug: str) -> str:
        if not seed_slug:
            raise ValueError("unknown seed: ")
        return f"<seed prompt for {seed_slug}>"

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: fake_loader,
            llm_call_dep=lambda _override=None: fake_llm,
            core_model_dep=lambda _override=None: "core-model",
        ),
    )
    return app


def test_post_preview_accepts_persona_override() -> None:
    """An inline persona_override drives the system prompt without a seed_slug."""
    captured: dict[str, str] = {}
    client = TestClient(_capture_prompt_app(captured))
    with client.stream(
        "POST",
        "/chat/preview",
        json={
            "history": [],
            "message": {"role": "user", "content": "hi"},
            "persona_override": {
                "name": "Aria",
                "identity_statement": "a calm, curious companion",
                "sentence_style": "short and warm",
            },
        },
    ) as response:
        assert response.status_code == 200
        b"".join(response.iter_bytes())

    prompt = captured["system_prompt"]
    # The override (not the seed loader) supplied the prompt.
    assert "Aria" in prompt
    assert "a calm, curious companion" in prompt
    assert "short and warm" in prompt
    assert "seed prompt" not in prompt


def test_post_preview_requires_seed_or_override() -> None:
    """A request with neither seed_slug nor persona_override is a 400."""
    captured: dict[str, str] = {}
    client = TestClient(_capture_prompt_app(captured))
    response = client.post(
        "/chat/preview",
        json={
            "history": [],
            "message": {"role": "user", "content": "hi"},
        },
    )
    assert response.status_code == 400
