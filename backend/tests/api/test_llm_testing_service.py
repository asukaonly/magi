"""Integration coverage for temporary LLM connection tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from aiohttp import web
from httpx import ASGITransport, AsyncClient

from magi.api.routers.llm import llm_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
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
@pytest.mark.parametrize("provider_type,model,cap", [
    (LLMProvider.CUSTOM, "local-model", "max_tokens"),
    (LLMProvider.OPENAI, "gpt-5.6-terra", "max_completion_tokens"),
])
async def test_provider_connection_sends_supported_parameters(
    provider_type: LLMProvider, model: str, cap: str,
) -> None:
    captured: dict[str, Any] = {}

    async def handle_chat(request: web.Request) -> web.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl-local",
                "object": "chat.completion",
                "created": 1,
                "model": model,
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
        api.include_router(
            _build_public_router(llm_router, _PUBLIC_ROUTE_METHODS["llm"]), prefix="/api/llm"
        )
        provider = _provider(
            provider_type,
            api_key="test-key" if provider_type == LLMProvider.OPENAI else "",
            base_url=f"http://127.0.0.1:{port}/v1",
            api_format="openai",
        )
        async with AsyncClient(
            transport=ASGITransport(app=api),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/llm/providers/test",
                json={
                    "provider_id": provider_type.value,
                    "provider": provider.model_dump(mode="json"),
                    "model": model,
                },
            )
    finally:
        await runner.cleanup()

    assert response.status_code == 200
    assert response.json()["data"]["preview"] == "local ready"
    payload = captured["payload"]
    assert payload["model"] == model
    cap_keys = {"max_tokens", "max_completion_tokens", "max_output_tokens"}
    assert cap_keys.intersection(payload) == {cap}
    assert payload[cap] == 32
    if provider_type == LLMProvider.OPENAI:
        assert payload["reasoning_effort"] == "none"
    else:
        assert captured["authorization"] is None
        assert "reasoning_effort" not in payload


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
