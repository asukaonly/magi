"""
Skills API Router

Provides endpoints for managing and executing skills:
- List all skills (metadata only)
- Refresh skill index
- Get skill details (including content)
- Execute a skill manually
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging
import getpass

from ..services.skills_runtime_service import (
    get_enabled_skill_names as _get_enabled_skill_names_service,
    get_skill_executor as _get_skill_executor_service,
    get_skill_indexer as _get_skill_indexer_service,
    get_skill_loader as _get_skill_loader_service,
    init_skills_module as _init_skills_module_service,
    register_enabled_skills as _register_enabled_skills_service,
)

logger = logging.getLogger(__name__)

skills_router = APIRouter(prefix="/api/skills", tags=["skills"])


# ============ data Models ============

class SkillMetadataResponse(BaseModel):
    """Skill metadataresponse"""
    name: str
    description: str
    category: Optional[str] = None
    argument_hint: Optional[str] = None
    user_invocable: bool = True
    context: Optional[str] = None
    agent: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    directory: str  # Skill directorypath
    enabled: bool = False


class SkillDetailResponse(BaseModel):
    """Skill 详情response（containsContent）"""
    name: str
    description: str
    category: Optional[str] = None
    argument_hint: Optional[str] = None
    user_invocable: bool = True
    context: Optional[str] = None
    agent: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    prompt_template: str  # process后的模板Content
    supporting_data: Dict[str, Any] = Field(default_factory=dict)


class SkillExecuteRequest(BaseModel):
    """Skill Executerequest"""
    arguments: List[str] = Field(default_factory=list, description="commandrowParameter")
    user_id: str = Field(default="anotttnymous", description="userid")
    user_message: str = Field(default="", description="原始User message")
    context: Dict[str, Any] = Field(default_factory=dict, description="额外context")


class SkillExecuteResponse(BaseModel):
    """Skill Executeresponse"""
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    mode: Optional[str] = None  # "direct" or "subagent"


def init_skills_module(llm_adapter=None):
    """Compatibility wrapper for shared skills runtime service."""
    _init_skills_module_service(llm_adapter=llm_adapter)


def get_skill_executor():
    """Get SkillExecutor instance from shared skills runtime service."""
    return _get_skill_executor_service()


# ============ API 端点 ============

@skills_router.get("/", response_model=List[SkillMetadataResponse])
async def list_skills():
    """
    getall Skills list（仅metadata）

    Returns:
        Skills metadatalist
    """
    skill_indexer = _get_skill_indexer_service()
    if skill_indexer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skills = skill_indexer.scan_all()
    enabled_skills = _get_enabled_skill_names_service()

    return [
        SkillMetadataResponse(
            name=name,
            description=skill.description,
            category=skill.category,
            argument_hint=skill.argument_hint,
            user_invocable=skill.user_invocable,
            context=skill.context,
            agent=skill.agent,
            tags=skill.tags,
            directory=str(skill.directory),
            enabled=name in enabled_skills,
        )
        for name, skill in skills.items()
    ]


@skills_router.post("/refresh", response_model=List[SkillMetadataResponse])
async def refresh_skills():
    """
    重new扫描 Skills directory

    Returns:
        update后的 Skills list
    """
    skill_indexer = _get_skill_indexer_service()
    if skill_indexer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skills = skill_indexer.refresh()
    _register_enabled_skills_service(skills)
    enabled_skills = _get_enabled_skill_names_service()

    return [
        SkillMetadataResponse(
            name=name,
            description=skill.description,
            category=skill.category,
            argument_hint=skill.argument_hint,
            user_invocable=skill.user_invocable,
            context=skill.context,
            agent=skill.agent,
            tags=skill.tags,
            directory=str(skill.directory),
            enabled=name in enabled_skills,
        )
        for name, skill in skills.items()
    ]


@skills_router.get("/{skill_name}", response_model=SkillDetailResponse)
async def get_skill_detail(skill_name: str):
    """
    get Skill 详情（contains完整Content）

    Args:
        skill_name: Skill Name

    Returns:
        Skill 详情
    """
    skill_loader = _get_skill_loader_service()
    if skill_loader is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skill_content = skill_loader.load_skill(skill_name)
    if not skill_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill not found: {skill_name}",
        )

    return SkillDetailResponse(
        name=skill_content.name,
        description=skill_content.frontmatter.description,
        category=skill_content.frontmatter.category,
        argument_hint=skill_content.frontmatter.argument_hint,
        user_invocable=skill_content.frontmatter.user_invocable,
        context=skill_content.frontmatter.context,
        agent=skill_content.frontmatter.agent,
        tags=skill_content.frontmatter.tags,
        prompt_template=skill_content.prompt_template,
        supporting_data=skill_content.supporting_data,
    )


@skills_router.post("/{skill_name}/execute", response_model=SkillExecuteResponse)
async def execute_skill(skill_name: str, request: SkillExecuteRequest):
    """
    手动Execute Skill

    Args:
        skill_name: Skill Name
        request: Executerequest

    Returns:
        Execution result
    """
    skill_executor = _get_skill_executor_service()
    if skill_executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    # buildExecutecontext
    import os
    context = {
        "user_id": request.user_id,
        "session_id": f"api_session_{request.user_id}",
        "user_message": request.user_message,
        "conversation_history": [],
        "env_vars": {
            "user": getpass.getuser(),
            "HOME": os.path.expanduser("~"),
            "PWD": os.getcwd(),
            "CLAUDE_session_id": f"api_session_{request.user_id}",
            "user_id": request.user_id,
        },
    }
    context.update(request.context)

    try:
        result = await skill_executor.execute(
            skill_name=skill_name,
            arguments=request.arguments,
            context=context,
        )

        return SkillExecuteResponse(
            success=result.success,
            response=result.content,
            error=result.error,
            execution_time=result.execution_time,
            mode=result.metadata.get("mode") if result.metadata else None,
        )

    except Exception as e:
        logger.error(f"Skill execution error: {e}")
        return SkillExecuteResponse(
            success=False,
            error=str(e),
            execution_time=0.0,
        )


@skills_router.get("/categories/list")
async def list_skill_categories():
    """
    get Skill 分Classlist

    Returns:
        分Classlist
    """
    skill_indexer = _get_skill_indexer_service()
    if skill_indexer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skills = skill_indexer.scan_all()
    categories = set(skill.category for skill in skills.values() if skill.category)

    return {
        "success": True,
        "data": list(categories),
    }
