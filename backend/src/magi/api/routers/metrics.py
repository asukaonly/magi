"""
metricmonitorAPIroute

提供系统performance、AgentState等monitormetric
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import psutil
import logging

logger = logging.getLogger(__name__)

metrics_router = APIRouter()


# ============ data Models ============

class SystemMetrics(BaseModel):
    """系统metric"""

    cpu_percent: float
    memory_percent: float
    memory_used: float
    memory_total: float
    disk_percent: float
    disk_used: float
    disk_total: float


class AgentMetrics(BaseModel):
    """Agentmetric"""

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
    get系统metric

    Returns:
        系统metric
    """
    # CPU使用率
    cpu_percent = psutil.cpu_percent(interval=0.1)

    # 内存使用率
    memory = psutil.virtual_memory()
    memory_percent = memory.percent
    memory_used = memory.used / (1024**3)  # GB
    memory_total = memory.total / (1024**3)  # GB

    # 磁盘使用率
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
    getallAgent的metric

    Returns:
        Agentmetriclist
    """
    # TODO: 从实际的Agent Managergetmetric
    # 这里Return模拟data
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
    get指定Agent的metric

    Args:
        agent_id: Agent id

    Returns:
        Agentmetric
    """
    # TODO: 从实际的Agent Managergetmetric
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
    getperformancemetric

    Returns:
        performancemetric
    """
    # TODO: 从monitor系统get实际performancedata
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
    get系统健康State

    Returns:
        健康State
    """
    # CPU使用率
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    # 判断健康State
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
