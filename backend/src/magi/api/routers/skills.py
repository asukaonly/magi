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


# ============ globalInstance（在应用启动时initialize）============

_skill_indexer = None
_skill_loader = None
_skill_executor = None


def init_skills_module(llm_adapter=None):
    """
    initialize Skills module

    Args:
        llm_adapter: LLM Adapter（用于 sub-agent Execute）
    """
    global _skill_indexer, _skill_loader, _skill_executor

    from ...skills.indexer import SkillIndexer
    from ...skills.loader import SkillLoader
    from ...skills.executor import SkillExecutor

    _skill_indexer = SkillIndexer()
    _skill_loader = SkillLoader(_skill_indexer)
    _skill_executor = SkillExecutor(_skill_loader, llm_adapter)

    # 初始扫描
    skills = _skill_indexer.scan_all()
    logger.info(f"Skills module initialized with {len(skills)} skills")


def get_skill_executor():
    """get SkillExecutor Instance"""
    return _skill_executor


# ============ API 端点 ============

@skills_router.get("/", response_model=List[SkillMetadataResponse])
async def list_skills():
    """
    getall Skills list（仅metadata）

    Returns:
        Skills metadatalist
    """
    if _skill_indexer is None:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skills = _skill_indexer.scan_all()

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
    if _skill_indexer is None:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skills = _skill_indexer.refresh()

    # 同时update tool_registry
    from ...tools.registry import tool_registry
    tool_registry.refresh_skills()

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
    if _skill_loader is None:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skill_content = _skill_loader.load_skill(skill_name)
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
    if _skill_executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
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
            "user": os.getenv("user") or os.getenv("username") or "unknotttwn",
            "HOME": os.path.expanduser("~"),
            "PWD": os.getcwd(),
            "CLAUDE_session_id": f"api_session_{request.user_id}",
            "user_id": request.user_id,
        },
    }
    context.update(request.context)

    try:
        result = await _skill_executor.execute(
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
    if _skill_indexer is None:
        raise HTTPException(
            status_code=status.HTTP_503_service_UNAVAILABLE,
            detail="Skills module not initialized",
        )

    skills = _skill_indexer.scan_all()
    categories = set(skill.category for skill in skills.values() if skill.category)

    return {
        "success": True,
        "data": list(categories),
    }
