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

from ...core.runtime_bindings import (
    require_skill_executor as _require_skill_executor_service,
    require_skill_indexer as _require_skill_indexer_service,
    require_skill_loader as _require_skill_loader_service,
)
from ...skills.service_access import (
    get_enabled_skill_names as _get_enabled_skill_names_service,
    register_enabled_skills as _register_enabled_skills_service,
)

logger = logging.getLogger(__name__)

skills_router = APIRouter(prefix="/api/skills", tags=["skills"])


# ============ data Models ============

class SkillMetadataResponse(BaseModel):
    """Skill metadata response."""
    name: str
    description: str
    category: Optional[str] = None
    argument_hint: Optional[str] = None
    user_invocable: bool = True
    context: Optional[str] = None
    agent: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    directory: str  # Skill directory path
    enabled: bool = False


class SkillDetailResponse(BaseModel):
    """Skill detail response (includes full content)."""
    name: str
    description: str
    category: Optional[str] = None
    argument_hint: Optional[str] = None
    user_invocable: bool = True
    context: Optional[str] = None
    agent: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    prompt_template: str  # Processed template content
    supporting_data: Dict[str, Any] = Field(default_factory=dict)


class SkillExecuteRequest(BaseModel):
    """Skill execution request."""
    arguments: List[str] = Field(default_factory=list, description="Command-line arguments")
    user_id: str = Field(default="anonymous", description="User ID")
    user_message: str = Field(default="", description="Original user message")
    context: Dict[str, Any] = Field(default_factory=dict, description="Extra context")


class SkillExecuteResponse(BaseModel):
    """Skill execution response."""
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    mode: Optional[str] = None  # "direct" or "subagent"
# ============ API endpoints ============

@skills_router.get("/", response_model=List[SkillMetadataResponse])
async def list_skills():
    """
    Get all skills list (metadata only).

    Returns:
        List of skill metadata.
    """
    try:
        skill_indexer = _require_skill_indexer_service()
    except RuntimeError:
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
    Rescan skills directory and return updated list.

    Returns:
        Updated list of skills.
    """
    try:
        skill_indexer = _require_skill_indexer_service()
    except RuntimeError:
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
    Get skill detail (includes full content).

    Args:
        skill_name: Skill name.

    Returns:
        Skill detail.
    """
    try:
        skill_loader = _require_skill_loader_service()
    except RuntimeError:
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
    Execute a skill manually.

    Args:
        skill_name: Skill name.
        request: Execution request.

    Returns:
        Execution result.
    """
    try:
        skill_executor = _require_skill_executor_service()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    # Build execution context
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
    Get list of skill categories.

    Returns:
        List of category names.
    """
    try:
        skill_indexer = _require_skill_indexer_service()
    except RuntimeError:
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
