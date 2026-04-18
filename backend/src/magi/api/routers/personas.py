"""Persona registry API routes.

Provides UUID-keyed CRUD, active persona management, and seed previews.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.logger import get_logger
from ...personality.persona_repository import PersonaRepository, PersonaSummary
from ...personality.persona_seed import list_seed_previews, seed_builtin_personas
from ...utils.runtime import get_runtime_paths

logger = get_logger(__name__)

personas_router = APIRouter()


# ---- response models ----

class PersonaSummaryModel(BaseModel):
    persona_id: str
    name: str
    slug: str
    locale: str
    avatar_path: str = ""
    group_name: str = "general"
    sort_order: int = 0
    is_builtin: bool = False
    description: str = ""


class PersonaDetailModel(BaseModel):
    persona_id: str
    name: str
    slug: str
    locale: str
    config: dict
    avatar_path: str = ""
    group_name: str = "general"
    sort_order: int = 0
    is_builtin: bool = False
    seed_slug: Optional[str] = None
    created_at: float = 0
    updated_at: float = 0


class PersonaListResponse(BaseModel):
    success: bool = True
    data: list[PersonaSummaryModel] = Field(default_factory=list)


class PersonaDetailResponse(BaseModel):
    success: bool = True
    data: Optional[PersonaDetailModel] = None


class PersonaCreateRequest(BaseModel):
    config_json: str
    locale: str = "en"
    slug: Optional[str] = None


class PersonaUpdateRequest(BaseModel):
    name: Optional[str] = None
    config_json: Optional[str] = None
    slug: Optional[str] = None
    avatar_path: Optional[str] = None
    sort_order: Optional[int] = None


class ActivePersonaRequest(BaseModel):
    persona_id: str


class ActivePersonaResponse(BaseModel):
    success: bool = True
    persona_id: Optional[str] = None


class SeedPreviewResponse(BaseModel):
    success: bool = True
    data: list[dict] = Field(default_factory=list)


class SeedResponse(BaseModel):
    success: bool = True
    created_ids: list[str] = Field(default_factory=list)


# ---- helpers ----

def _get_repo() -> PersonaRepository:
    return PersonaRepository(str(get_runtime_paths().persona_registry_db_path))


# ---- endpoints ----

@personas_router.get("/", response_model=PersonaListResponse)
async def list_personas():
    """List all registered personas."""
    repo = _get_repo()
    await repo.init()
    summaries = await repo.list_all()
    return PersonaListResponse(
        data=[PersonaSummaryModel(**s.__dict__) for s in summaries],
    )


@personas_router.get("/active", response_model=ActivePersonaResponse)
async def get_active_persona():
    """Return the active persona ID."""
    repo = _get_repo()
    await repo.init()
    active_id = await repo.get_active_id()
    return ActivePersonaResponse(persona_id=active_id)


@personas_router.put("/active", response_model=ActivePersonaResponse)
async def set_active_persona(payload: ActivePersonaRequest):
    """Switch the active persona."""
    repo = _get_repo()
    await repo.init()
    try:
        await repo.set_active(payload.persona_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Persona not found")
    return ActivePersonaResponse(persona_id=payload.persona_id)


@personas_router.get("/seed-previews", response_model=SeedPreviewResponse)
async def get_seed_previews(locale: str = "en"):
    """Return lightweight previews of available seed personas."""
    previews = await list_seed_previews(locale)
    return SeedPreviewResponse(data=previews)


@personas_router.post("/seed", response_model=SeedResponse)
async def seed_personas(locale: str = "en"):
    """Seed builtin personas from bundled presets (idempotent)."""
    repo = _get_repo()
    await repo.init()
    created_ids = await seed_builtin_personas(repo, locale)
    return SeedResponse(created_ids=created_ids)


@personas_router.post("/", response_model=PersonaDetailResponse, status_code=201)
async def create_persona(payload: PersonaCreateRequest):
    """Create a new custom persona."""
    repo = _get_repo()
    await repo.init()
    try:
        json.loads(payload.config_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid config_json")
    persona_id = await repo.create(
        config_json=payload.config_json,
        locale=payload.locale,
        slug=payload.slug,
    )
    record = await repo.get(persona_id)
    return PersonaDetailResponse(
        data=PersonaDetailModel(
            persona_id=record.persona_id,
            name=record.name,
            slug=record.slug,
            locale=record.locale,
            config=record.config.to_dict(),
            avatar_path=record.avatar_path,
            group_name=record.group_name,
            sort_order=record.sort_order,
            is_builtin=record.is_builtin,
            seed_slug=record.seed_slug,
            created_at=record.created_at,
            updated_at=record.updated_at,
        ),
    )


@personas_router.get("/{persona_id}", response_model=PersonaDetailResponse)
async def get_persona(persona_id: str):
    """Get full persona detail by ID."""
    repo = _get_repo()
    await repo.init()
    try:
        record = await repo.get(persona_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Persona not found")
    return PersonaDetailResponse(
        data=PersonaDetailModel(
            persona_id=record.persona_id,
            name=record.name,
            slug=record.slug,
            locale=record.locale,
            config=record.config.to_dict(),
            avatar_path=record.avatar_path,
            group_name=record.group_name,
            sort_order=record.sort_order,
            is_builtin=record.is_builtin,
            seed_slug=record.seed_slug,
            created_at=record.created_at,
            updated_at=record.updated_at,
        ),
    )


@personas_router.put("/{persona_id}", response_model=PersonaDetailResponse)
async def update_persona(persona_id: str, payload: PersonaUpdateRequest):
    """Update mutable fields of an existing persona."""
    repo = _get_repo()
    await repo.init()
    try:
        await repo.update(
            persona_id,
            name=payload.name,
            config_json=payload.config_json,
            slug=payload.slug,
            avatar_path=payload.avatar_path,
            sort_order=payload.sort_order,
        )
        record = await repo.get(persona_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Persona not found")
    return PersonaDetailResponse(
        data=PersonaDetailModel(
            persona_id=record.persona_id,
            name=record.name,
            slug=record.slug,
            locale=record.locale,
            config=record.config.to_dict(),
            avatar_path=record.avatar_path,
            group_name=record.group_name,
            sort_order=record.sort_order,
            is_builtin=record.is_builtin,
            seed_slug=record.seed_slug,
            created_at=record.created_at,
            updated_at=record.updated_at,
        ),
    )


@personas_router.delete("/{persona_id}")
async def delete_persona(persona_id: str):
    """Delete a persona (cannot delete the active one)."""
    repo = _get_repo()
    await repo.init()
    try:
        await repo.delete(persona_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Persona not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"success": True}
