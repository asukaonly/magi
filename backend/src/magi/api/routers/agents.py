"""
Agent管理API路由

提供Agent的CRUD操作和启停控制
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

agents_router = APIRouter()


# ============ 数据模型 ============

class AgentCreateRequest(BaseModel):
    """创建Agent请求"""

    name: str = Field(..., description="Agent名称")
    agent_type: str = Field(..., description="Agent类型: master/task/worker")
    config: Dict[str, Any] = Field(default_factory=dict, description="Agent配置")


class AgentUpdateRequest(BaseModel):
    """更新Agent请求"""

    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    """Agent响应"""

    id: str
    name: str
    agent_type: str
    state: str
    config: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None


class AgentActionRequest(BaseModel):
    """Agent操作请求"""

    action: str = Field(..., description="操作类型: start/stop/restart")


# ============ 内存存储（开发用） ============

# TODO: 替换为实际的Agent Manager
_agents_store: Dict[str, Dict] = {}


# ============ API端点 ============

@agents_router.get("/", response_model=List[AgentResponse])
async def list_agents(
    agent_type: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    获取Agent列表

    Args:
        agent_type: 过滤Agent类型
        state: 过滤Agent状态
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        Agent列表
    """
    agents = list(_agents_store.values())

    # 过滤
    if agent_type:
        agents = [a for a in agents if a["agent_type"] == agent_type]
    if state:
        agents = [a for a in agents if a["state"] == state]

    # 分页
    total = len(agents)
    agents = agents[offset:offset + limit]

    return agents


@agents_router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """
    获取Agent详情

    Args:
        agent_id: Agent ID

    Returns:
        Agent详情
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    return _agents_store[agent_id]


@agents_router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(request: AgentCreateRequest):
    """
    创建Agent

    Args:
        request: 创建请求

    Returns:
        创建的Agent
    """
    agent_id = f"agent_{len(_agents_store) + 1}"

    agent = {
        "id": agent_id,
        "name": request.name,
        "agent_type": request.agent_type,
        "state": "stopped",
        "config": request.config,
        "created_at": datetime.now(),
        "updated_at": None,
    }

    _agents_store[agent_id] = agent
    logger.info(f"Created agent: {agent_id}")

    return agent


@agents_router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: str, request: AgentUpdateRequest):
    """
    更新Agent

    Args:
        agent_id: Agent ID
        request: 更新请求

    Returns:
        更新后的Agent
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    agent = _agents_store[agent_id]

    # 更新字段
    if request.name:
        agent["name"] = request.name
    if request.config:
        agent["config"].update(request.config)

    agent["updated_at"] = datetime.now()

    logger.info(f"Updated agent: {agent_id}")
    return agent


@agents_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str):
    """
    删除Agent

    Args:
        agent_id: Agent ID
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    del _agents_store[agent_id]
    logger.info(f"Deleted agent: {agent_id}")


@agents_router.post("/{agent_id}/action")
async def agent_action(agent_id: str, request: AgentActionRequest):
    """
    执行Agent操作（启动/停止/重启）

    Args:
        agent_id: Agent ID
        request: 操作请求

    Returns:
        操作结果
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    agent = _agents_store[agent_id]

    # 执行操作
    if request.action == "start":
        if agent["state"] == "running":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Agent {agent_id} is already running",
            )
        agent["state"] = "running"
        logger.info(f"Started agent: {agent_id}")

    elif request.action == "stop":
        if agent["state"] == "stopped":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Agent {agent_id} is already stopped",
            )
        agent["state"] = "stopped"
        logger.info(f"Stopped agent: {agent_id}")

    elif request.action == "restart":
        agent["state"] = "running"
        logger.info(f"Restarted agent: {agent_id}")

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action: {request.action}",
        )

    agent["updated_at"] = datetime.now()

    return {
        "success": True,
        "message": f"Agent {agent_id} {request.action}ed successfully",
        "data": agent,
    }


@agents_router.get("/{agent_id}/stats")
async def get_agent_stats(agent_id: str):
    """
    获取Agent统计信息

    Args:
        agent_id: Agent ID

    Returns:
        Agent统计信息
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # TODO: 返回实际的统计信息（pending任务数、处理次数等）
    return {
        "success": True,
        "data": {
            "agent_id": agent_id,
            "pending_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "average_processing_time": 0.0,
        },
    }
