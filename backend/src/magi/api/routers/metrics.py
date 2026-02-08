"""
指标监控API路由

提供系统性能、Agent状态等监控指标
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import psutil
import logging

logger = logging.getLogger(__name__)

metrics_router = APIRouter()


# ============ 数据模型 ============

class SystemMetrics(BaseModel):
    """系统指标"""

    cpu_percent: float
    memory_percent: float
    memory_used: float
    memory_total: float
    disk_percent: float
    disk_used: float
    disk_total: float


class AgentMetrics(BaseModel):
    """Agent指标"""

    agent_id: str
    agent_name: str
    state: str
    pending_tasks: int
    completed_tasks: int
    failed_tasks: int
    average_processing_time: float


# ============ API端点 ============

@metrics_router.get("/system", response_model=SystemMetrics)
async def get_system_metrics():
    """
    获取系统指标

    Returns:
        系统指标
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
    获取所有Agent的指标

    Returns:
        Agent指标列表
    """
    # TODO: 从实际的Agent Manager获取指标
    # 这里返回模拟数据
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
    获取指定Agent的指标

    Args:
        agent_id: Agent ID

    Returns:
        Agent指标
    """
    # TODO: 从实际的Agent Manager获取指标
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
    获取性能指标

    Returns:
        性能指标
    """
    # TODO: 从监控系统获取实际性能数据
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
    获取系统健康状态

    Returns:
        健康状态
    """
    # CPU使用率
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    # 判断健康状态
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
