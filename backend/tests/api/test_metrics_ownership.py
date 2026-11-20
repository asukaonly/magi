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


def test_daily_estimates_and_unpriced_reasons(metrics_client, monkeypatch):
    from datetime import date, datetime, timedelta
    import httpx
    from magi.llm import usage_cost_report

    client, store = metrics_client
    first = date.today() - timedelta(days=3)
    second = first + timedelta(days=1)
    days = [first.isoformat(), second.isoformat()]
    rates_requested = []

    async def daily_rates(quote, missing):
        rates_requested.append((quote, missing))
        return [(day, quote, rate, day) for day, rate in zip(days, (6, 7))]

    async def seed():
        for index, (day, currency, amount, success, usage) in enumerate([
            (first, "USD", 2, True, True), (second, "USD", 3, True, True),
            (first, "CNY", 12, True, True), (first, None, None, False, False),
            (second, None, None, True, False), (second, None, None, True, True),
        ]):
            await store.record_call(dict(request_id=str(index), provider="p", model="m", request_kind="chat",
                cost_currency=currency, cost_usd=amount, success=success, usage_available=usage,
                created_at=datetime.combine(day, datetime.min.time()).timestamp()))

    asyncio.run(seed())
    monkeypatch.setattr(usage_cost_report, "_fetch_daily_rates", daily_rates)
    route = "/api/metrics/llm/usage/summary?include_estimates=true"
    data = client.get(route).json()["data"]
    assert rates_requested == [("CNY", set(days))]
    assert data["totals"]["display_costs"] == {"CNY": 45, "USD": 7}
    assert data["totals"]["unpriced_calls"] == 3
    assert data["totals"]["unpriced_failed_without_usage"] == 1
    assert data["totals"]["unpriced_success_without_usage"] == 1
    assert data["daily_display_costs"][days[0]] == {"CNY": 24, "USD": 4}
    for group in ("models", "providers", "request_kinds"):
        assert data[group][0]["display_costs"] == data["totals"]["display_costs"]

    async def offline(quote, missing):
        assert quote == "EUR"
        raise httpx.ConnectError("Offline")

    monkeypatch.setattr(usage_cost_report, "_fetch_daily_rates", offline)
    asyncio.run(store.record_call(dict(request_id="eur", provider="e", model="e", request_kind="e",
        cost_currency="EUR", cost_usd=2, created_at=datetime.combine(first, datetime.min.time()).timestamp())))
    data = client.get(route).json()["data"]
    assert data["totals"]["display_costs"] == {"CNY": None, "USD": None}
    known = next(row for row in data["providers"] if row["provider"] == "p")
    assert known["display_costs"] == {"CNY": 45, "USD": 7}
    assert {row["currency"] for row in data["totals"]["cost_by_currency"]} == {"CNY", "USD", "EUR"}
