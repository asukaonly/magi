"""Public metrics routes read persisted owner data through the runtime binding."""
import asyncio
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routers import metrics
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.llm.usage_store import LLMUsageStore


@pytest.fixture
def metrics_client(tmp_path, ensure_db_schema, monkeypatch):
    path = tmp_path / "usage.db"
    ensure_db_schema("llm_usage", str(path))
    store = LLMUsageStore(path)
    monkeypatch.setattr(metrics, "get_api_runtime_dependencies", lambda: SimpleNamespace(llm_usage_store=store))
    app = FastAPI()
    app.include_router(_build_public_router(metrics.metrics_router, _PUBLIC_ROUTE_METHODS["metrics"]), prefix="/api/metrics")
    with TestClient(app) as client:
        yield client, store


def test_summary_and_timeseries_keep_usage_and_currency(metrics_client):
    client, store = metrics_client
    async def seed():
        for index, currency in enumerate(("USD", "CNY")):
            await store.record_call({"request_id": f"call-{index}", "provider": "provider", "model": "model", "request_kind": "chat", "success": True, "usage_available": True, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost_usd": 1.5, "cost_currency": currency, "created_at": time.time()})
    asyncio.run(seed())
    response = client.get("/api/metrics/llm/usage/summary?days=500&model_limit=1")
    assert response.status_code == 200
    summary = response.json()["data"]
    assert summary["window_days"] == 365
    assert summary["totals"]["total_calls"] == 2
    assert summary["totals"]["total_tokens"] == 30
    assert {item["currency"] for item in summary["totals"]["cost_by_currency"]} == {"USD", "CNY"}
    response = client.get("/api/metrics/llm/usage/timeseries?days=0")
    assert response.status_code == 200
    assert response.json()["data"]["window_days"] == 1
    assert sum(item["total_tokens"] for item in response.json()["data"]["points"]) == 30


def test_metrics_unavailable_is_not_zero_usage(metrics_client, monkeypatch):
    client, _ = metrics_client
    monkeypatch.setattr(metrics, "get_api_runtime_dependencies", lambda: SimpleNamespace(llm_usage_store=None))
    assert client.get("/api/metrics/llm/usage/summary").status_code == 503
    assert client.get("/api/metrics/llm/usage/timeseries").status_code == 503
