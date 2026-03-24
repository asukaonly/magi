"""
Metrics Monitoring API Routes

Provides system performance, agent state, and other monitoring metrics.
"""
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from typing import List
import psutil
import logging

from ...llm import get_llm_usage_store
from ..services.metrics_overview_service import build_runtime_overview

logger = logging.getLogger(__name__)

metrics_router = APIRouter()


# ============ Data Models ============

class SystemMetrics(BaseModel):
    """System metrics"""

    cpu_percent: float
    memory_percent: float
    memory_used: float
    memory_total: float
    disk_percent: float
    disk_used: float
    disk_total: float


class AgentMetrics(BaseModel):
    """Agent metrics"""

    agent_id: str
    agent_name: str
    state: str
    pending_tasks: int
    completed_tasks: int
    failed_tasks: int
    average_processing_time: float


# ============ API Endpoints ============

@metrics_router.get("/system", response_model=SystemMetrics)
async def get_system_metrics():
    """
    Get system metrics

    Returns:
        System metrics
    """
    # CPU usage
    cpu_percent = psutil.cpu_percent(interval=0.1)

    # Memory usage
    memory = psutil.virtual_memory()
    memory_percent = memory.percent
    memory_used = memory.used / (1024**3)  # GB
    memory_total = memory.total / (1024**3)  # GB

    # Disk usage
    disk = psutil.disk_usage('/')
    disk_percent = disk.percent
    disk_used = disk.used / (1024**3)  # GB
    disk_total = disk.total / (1024**3)  # GB

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used": round(memory_used, 2),
        "memory_total": round(memory_total, 2),
        "disk_percent": disk_percent,
        "disk_used": round(disk_used, 2),
        "disk_total": round(disk_total, 2),
    }


@metrics_router.get("/agents", response_model=List[AgentMetrics])
async def get_agents_metrics():
    """
    Get all agent metrics

    Returns:
        Agent metrics list
    """
    # TODO: Get metrics from actual Agent Manager
    # Returning simulated data here
    return [
        {
            "agent_id": "agent_1",
            "agent_name": "master-agent",
            "state": "running",
            "pending_tasks": 5,
            "completed_tasks": 100,
            "failed_tasks": 2,
            "average_processing_time": 1.5,
        },
        {
            "agent_id": "agent_2",
            "agent_name": "task-agent-0",
            "state": "running",
            "pending_tasks": 3,
            "completed_tasks": 80,
            "failed_tasks": 1,
            "average_processing_time": 2.0,
        },
    ]


@metrics_router.get("/agents/{agent_id}", response_model=AgentMetrics)
async def get_agent_metrics(agent_id: str):
    """
    Get metrics for a specific agent

    Args:
        agent_id: Agent ID

    Returns:
        Agent metrics
    """
    # TODO: Get metrics from actual Agent Manager
    return {
        "agent_id": agent_id,
        "agent_name": f"agent-{agent_id}",
        "state": "running",
        "pending_tasks": 5,
        "completed_tasks": 100,
        "failed_tasks": 2,
        "average_processing_time": 1.5,
    }


@metrics_router.get("/performance")
async def get_performance_metrics():
    """
    Get performance metrics

    Returns:
        Performance metrics
    """
    # TODO: Get actual performance data from monitoring system
    return {
        "success": True,
        "data": {
            "total_requests": 1000,
            "requests_per_second": 10.5,
            "average_response_time": 0.5,
            "error_rate": 0.01,
            "active_connections": 50,
        },
    }


@metrics_router.get("/health")
async def get_health_status():
    """
    Get system health status

    Returns:
        Health status
    """
    # CPU usage
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    # Determine health status
    is_healthy = cpu_percent < 90 and memory.percent < 90

    status = "healthy" if is_healthy else "warning"

    return {
        "success": True,
        "data": {
            "status": status,
            "checks": {
                "cpu": {
                    "status": "ok" if cpu_percent < 90 else "warning",
                    "value": cpu_percent,
                },
                "memory": {
                    "status": "ok" if memory.percent < 90 else "warning",
                    "value": memory.percent,
                },
            },
        },
    }


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
