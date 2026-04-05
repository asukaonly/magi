"""Tests for the api.forward IPC handler — ASGI dispatch round-trip."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from magi.ipc.handlers import ApiForwardHandler


@pytest.fixture
def sample_app() -> FastAPI:
    """Minimal FastAPI app for testing the forward handler."""
    app = FastAPI()

    @app.get("/api/echo")
    async def echo_get():
        return {"method": "GET", "ok": True}

    @app.post("/api/echo")
    async def echo_post(data: dict | None = None):
        return {"method": "POST", "body": data, "ok": True}

    @app.get("/api/with-query")
    async def with_query(foo: str = "default"):
        return {"foo": foo}

    @app.delete("/api/items/{item_id}")
    async def delete_item(item_id: str):
        return {"deleted": item_id}

    return app


@pytest.fixture
def forward_handler(sample_app: FastAPI) -> ApiForwardHandler:
    return ApiForwardHandler(sample_app)


class TestApiForwardHandler:
    @pytest.mark.asyncio
    async def test_get_request(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle({
            "method": "GET",
            "path": "/api/echo",
        })
        assert result["status"] == 200
        assert result["body"]["method"] == "GET"
        assert result["body"]["ok"] is True

    @pytest.mark.asyncio
    async def test_post_with_body(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle({
            "method": "POST",
            "path": "/api/echo",
            "body": {"key": "value"},
        })
        assert result["status"] == 200
        assert result["body"]["method"] == "POST"
        assert result["body"]["body"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_query_string(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle({
            "method": "GET",
            "path": "/api/with-query",
            "query": "foo=bar",
        })
        assert result["status"] == 200
        assert result["body"]["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_delete_with_path_param(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle({
            "method": "DELETE",
            "path": "/api/items/abc123",
        })
        assert result["status"] == 200
        assert result["body"]["deleted"] == "abc123"

    @pytest.mark.asyncio
    async def test_not_found(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle({
            "method": "GET",
            "path": "/api/nonexistent",
        })
        assert result["status"] == 404

    @pytest.mark.asyncio
    async def test_missing_params(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle(None)
        assert result["status"] == 400
