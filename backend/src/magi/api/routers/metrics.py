"""Product metrics read through their data owners."""
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..runtime_dependencies import get_api_runtime_dependencies

metrics_router = APIRouter()


def _usage_store():
    store = get_api_runtime_dependencies().llm_usage_store
    if store is None:
        raise HTTPException(status_code=503, detail="LLM usage storage is unavailable")
    return store


@metrics_router.get("/llm/usage/summary")
async def llm_usage_summary(days: int = Query(default=7), model_limit: int = Query(default=8)) -> dict[str, Any]:
    data = await _usage_store().get_summary(days=max(1, min(365, days)), model_limit=max(1, min(50, model_limit)))
    return {"success": True, "message": "LLM usage summary loaded", "data": data}


@metrics_router.get("/llm/usage/timeseries")
async def llm_usage_timeseries(days: int = Query(default=7)) -> dict[str, Any]:
    days = max(1, min(365, days))
    points = await _usage_store().get_timeseries(days=days)
    return {"success": True, "message": "LLM usage timeseries loaded", "data": {"window_days": days, "points": points}}
