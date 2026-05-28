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

    def fake_core_model() -> str:
        return "test-core-model"

    app = FastAPI()
    app.include_router(
        build_default_chat_preview_router(
            persona_loader_dep=lambda: fake_loader,
            llm_call_dep=lambda: fake_llm,
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
