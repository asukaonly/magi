"""
Skills API Router

Provides endpoints for managing and executing skills:
- List all skills (metadata only)
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
import logging

from ... import i18n as core_i18n
from ...skills.provider import resolve_skill_indexer as _resolve_skill_indexer_service
from ...skills.service_access import (
    get_enabled_skill_names as _get_enabled_skill_names_service,
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


# ============ API endpoints ============


@skills_router.get("/", response_model=List[SkillMetadataResponse])
async def list_skills():
    """
    Get all skills list (metadata only).

    Returns:
        List of skill metadata.
    """
    try:
        skill_indexer = _resolve_skill_indexer_service()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "skills.errors.module_uninitialized", fallback="Skills module not initialized"
            ),
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
