from __future__ import annotations

import pytest

from magi.api.routers import metrics as metrics_router


class _FakeUsageStore:
    async def get_summary(self, *, days: int, model_limit: int) -> dict[str, object]:
        assert days == 30
        assert model_limit == 8
        return {
            "window_days": days,
            "totals": {
                "total_calls": 12,
                "successful_calls": 11,
                "failed_calls": 1,
                "calls_with_usage": 12,
                "prompt_tokens": 1200,
                "completion_tokens": 400,
                "total_tokens": 1600,
                "avg_latency_ms": 980.5,
                "avg_ttft_ms": 420.0,
                "total_cost_usd": 1.245,
            },
            "providers": [
                {
                    "provider": "openai",
                    "calls": 12,
                    "successful_calls": 11,
                    "failed_calls": 1,
                    "prompt_tokens": 1200,
                    "completion_tokens": 400,
                    "total_tokens": 1600,
                    "avg_latency_ms": 980.5,
                    "avg_ttft_ms": 420.0,
                    "cost_usd": 1.245,
                }
            ],
            "models": [],
            "request_kinds": [],
        }

    async def get_timeseries(self, *, days: int) -> list[dict[str, object]]:
        assert days == 30
        return [
            {
                "day": "2026-03-24",
                "calls": 12,
                "prompt_tokens": 1200,
                "completion_tokens": 400,
                "total_tokens": 1600,
                "cost_usd": 1.245,
            }
        ]


@pytest.mark.asyncio
async def test_get_llm_usage_summary_returns_extended_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_router, "get_llm_usage_store", lambda: _FakeUsageStore())

    response = await metrics_router.get_llm_usage_summary(days=30, model_limit=8)

    assert response["success"] is True
    assert response["data"]["totals"]["avg_ttft_ms"] == 420.0
    assert response["data"]["totals"]["total_cost_usd"] == 1.245
    assert response["data"]["providers"][0]["failed_calls"] == 1
    assert response["data"]["providers"][0]["cost_usd"] == 1.245


@pytest.mark.asyncio
async def test_get_llm_usage_timeseries_returns_cost_series(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_router, "get_llm_usage_store", lambda: _FakeUsageStore())

    response = await metrics_router.get_llm_usage_timeseries(days=30)

    assert response["success"] is True
    assert response["data"]["window_days"] == 30
    assert response["data"]["points"][0]["cost_usd"] == 1.245
