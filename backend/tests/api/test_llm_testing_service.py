"""Integration coverage for temporary LLM connection tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from aiohttp import web
from httpx import ASGITransport, AsyncClient

from magi.api.routers.llm import llm_router
from magi.config.models import LLMProvider, LLMProviderSettings
from magi.llm.draft import build_adapter_from_provider


def _provider(
    provider_type: LLMProvider,
    *,
    api_key: str = "",
    base_url: str = "",
    api_format: str | None = None,
) -> LLMProviderSettings:
    provider = LLMProviderSettings(
        enabled=True,
        provider_type=provider_type,
        display_name=provider_type.value,
        api_key=api_key,
        base_url=base_url,
        api_format=api_format,
        custom_models=["local-model"] if provider_type == LLMProvider.CUSTOM else [],
        custom_default_model="local-model" if provider_type == LLMProvider.CUSTOM else None,
    )
    provider.services.chat.enabled = True
    provider.services.chat.api_key = api_key
    provider.services.chat.base_url = base_url
    return provider


@pytest.mark.asyncio
async def test_keyless_custom_openai_provider_calls_local_endpoint() -> None:
    captured: dict[str, Any] = {}

    async def handle_chat(request: web.Request) -> web.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl-local",
                "object": "chat.completion",
                "created": 1,
                "model": "local-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "local ready"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handle_chat)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets if site._server is not None else []
    assert sockets
    port = sockets[0].getsockname()[1]

    try:
        api = FastAPI()
        api.include_router(llm_router, prefix="/llm")
        provider = _provider(
            LLMProvider.CUSTOM,
            base_url=f"http://127.0.0.1:{port}/v1",
            api_format="openai",
        )
        async with AsyncClient(
            transport=ASGITransport(app=api),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/llm/providers/test",
                json={
                    "provider_id": "custom",
                    "provider": provider.model_dump(mode="json"),
                    "model": "local-model",
                },
            )
    finally:
        await runner.cleanup()

    assert response.status_code == 200
    assert response.json()["data"]["preview"] == "local ready"
    assert captured["authorization"] is None
    assert captured["payload"]["model"] == "local-model"


def test_builtin_provider_still_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key is required"):
        build_adapter_from_provider(
            _provider(
                LLMProvider.OPENAI,
                base_url="https://api.openai.com/v1",
            ),
            model="gpt-4o-mini",
            proxy_url=None,
        )
