"""
Agent管理APIroute

提供Agent的CRUDoperationand启停控制
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

agents_router = APIRouter()


# ============ data Models ============

class AgentCreateRequest(BaseModel):
    """createAgentrequest"""

    name: str = Field(..., description="AgentName")
    agent_type: str = Field(..., description="Agenttype: master/task/worker")
    config: Dict[str, Any] = Field(default_factory=dict, description="AgentConfiguration")


class AgentUpdateRequest(BaseModel):
    """updateAgentrequest"""

    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    """Agentresponse"""

    id: str
    name: str
    agent_type: str
    state: str
    config: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None


class AgentActionRequest(BaseModel):
    """Agentoperationrequest"""

    action: str = Field(..., description="operationtype: start/stop/restart")


# ============ 内存storage（开发用） ============

# TODO: replace为实际的Agent Manager
_agents_store: Dict[str, Dict] = {}


# ============ API Endpoints ============

@agents_router.get("/", response_model=List[AgentResponse])
async def list_agents(
    agent_type: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    getAgentlist

    Args:
        agent_type: filterAgenttype
        state: filterAgentState
        limit: Returnquantitylimitation
        offset: offset量

    Returns:
        Agentlist
    """
    agents = list(_agents_store.values())

    # filter
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
    getAgent详情

    Args:
        agent_id: Agent id

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
    createAgent

    Args:
        request: createrequest

    Returns:
        create的Agent
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
    updateAgent

    Args:
        agent_id: Agent id
        request: updaterequest

    Returns:
        update后的Agent
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    agent = _agents_store[agent_id]

    # updatefield
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
    deleteAgent

    Args:
        agent_id: Agent id
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
    ExecuteAgentoperation（启动/stop/重启）

    Args:
        agent_id: Agent id
        request: operationrequest

    Returns:
        operationResult
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    agent = _agents_store[agent_id]

    # Executeoperation
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
            detail=f"Unknotttwn action: {request.action}",
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
    getAgentstatisticsinfo

    Args:
        agent_id: Agent id

    Returns:
        Agentstatisticsinfo
    """
    if agent_id not in _agents_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # TODO: Return实际的statisticsinfo（pending任务数、processcount等）
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
