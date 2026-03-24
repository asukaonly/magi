"""
Metrics Monitoring API Routes

Provides system performance, agent state, and other monitoring metrics.
"""
from fastapi import APIRouter, Query, Request
import logging

from ...llm import get_llm_usage_store
from ..services.metrics_overview_service import build_runtime_overview

logger = logging.getLogger(__name__)

metrics_router = APIRouter()


@metrics_router.get("/llm/usage/summary")
async def get_llm_usage_summary(
    days: int = Query(default=7, ge=1, le=365),
    model_limit: int = Query(default=8, ge=1, le=50),
):
    """Get aggregated LLM usage summary."""
    store = get_llm_usage_store()
    summary = await store.get_summary(days=days, model_limit=model_limit)
    return {
        "success": True,
        "message": "LLM usage summary loaded",
        "data": summary,
    }


@metrics_router.get("/llm/usage/timeseries")
async def get_llm_usage_timeseries(
    days: int = Query(default=7, ge=1, le=365),
):
    """Get daily LLM usage trend."""
    store = get_llm_usage_store()
    series = await store.get_timeseries(days=days)
    return {
        "success": True,
        "message": "LLM usage timeseries loaded",
        "data": {
            "window_days": days,
            "points": series,
        },
    }


@metrics_router.get("/runtime/overview")
async def get_runtime_overview(request: Request):
    """Get a settings-facing runtime overview payload."""
    overview = await build_runtime_overview(request.app)
    return {
        "success": True,
        "message": "Runtime overview loaded",
        "data": overview,
    }
