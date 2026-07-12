"""Persona registry API routes.

Provides UUID-keyed CRUD, active persona management, and seed previews.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.logger import get_logger
from ...personality.persona_repository import PersonaRecord, PersonaRepository
from ... import i18n as core_i18n
from ...personality.persona_seed import list_seed_previews, resolve_locale, seed_builtin_personas
from ...utils.runtime import get_runtime_paths

logger = get_logger(__name__)

personas_router = APIRouter()
_ACTIVE_PERSONA_SWITCH_LOCK = asyncio.Lock()


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
    seed_slug: Optional[str] = None
    description: str = ""
    deleted_at: Optional[float] = None


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
    deleted_at: Optional[float] = None


class PersonaListResponse(BaseModel):
    success: bool = True
    data: list[PersonaSummaryModel] = Field(default_factory=list)


class PersonaDetailResponse(BaseModel):
    success: bool = True
    data: Optional[PersonaDetailModel] = None


class PersonaCreateRequest(BaseModel):
    persona_id: Optional[UUID] = None
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


def _request_language(request: Request) -> str | None:
    return request.headers.get("Accept-Language") or None


async def _sync_registered_builtin_personas(repo: PersonaRepository) -> None:
    summaries = await repo.list_all(include_deleted=True)
    locales = {
        item.locale
        for item in summaries
        if item.is_builtin and item.seed_slug and item.deleted_at is None
    }
    if not locales:
        locales = {resolve_locale(core_i18n.get_preferred_language())}
    for locale in sorted(locales):
        await seed_builtin_personas(repo, locale)


async def _restore_previous_persona(
    repo: PersonaRepository,
    previous_record: PersonaRecord | None,
    memory: Any | None,
) -> None:
    """Compensate a failed live persona switch back to its previous state."""
    from ...personality.active_persona import (
        clear_active_persona,
        set_current_personality,
    )

    rollback_errors: list[str] = []
    try:
        if previous_record is None:
            await repo.clear_active()
        else:
            await repo.set_active(previous_record.persona_id)
    except Exception as exc:
        rollback_errors.append(f"registry: {exc}")

    try:
        if previous_record is None:
            clear_active_persona()
        else:
            set_current_personality(previous_record.slug, config=previous_record.config)
    except Exception as exc:
        rollback_errors.append(f"cache: {exc}")

    if memory is not None and previous_record is not None:
        try:
            await memory.reload_personality(
                previous_record.slug,
                personality_config=previous_record.config,
            )
        except Exception as exc:
            rollback_errors.append(f"live memory: {exc}")

    if rollback_errors:
        logger.error(
            "Failed to fully restore previous persona state: %s",
            "; ".join(rollback_errors),
        )


async def _restore_previous_persona_safely(
    repo: PersonaRepository,
    previous_record: PersonaRecord | None,
    memory: Any | None,
) -> None:
    """Finish compensation even if the request is cancelled while restoring."""
    restore_task = asyncio.create_task(
        _restore_previous_persona(repo, previous_record, memory)
    )
    cancelled_while_restoring = False
    while not restore_task.done():
        try:
            await asyncio.shield(restore_task)
        except asyncio.CancelledError:
            cancelled_while_restoring = True
    try:
        restore_task.result()
    except Exception:
        logger.exception("Unexpected error while restoring a persona switch")
    if cancelled_while_restoring:
        raise asyncio.CancelledError


# ---- endpoints ----

@personas_router.get("/", response_model=PersonaListResponse)
async def list_personas(include_deleted: bool = False):
    """List all registered personas."""
    repo = _get_repo()
    await repo.init()
    await _sync_registered_builtin_personas(repo)
    summaries = await repo.list_all(include_deleted=include_deleted)
    return PersonaListResponse(
        data=[PersonaSummaryModel(**asdict(s)) for s in summaries],
    )


@personas_router.get("/active", response_model=ActivePersonaResponse)
async def get_active_persona():
    """Return the active persona ID."""
    repo = _get_repo()
    await repo.init()
    active_id = await repo.get_active_id()
    return ActivePersonaResponse(persona_id=active_id)


@personas_router.put("/active", response_model=ActivePersonaResponse)
async def set_active_persona(request: Request, payload: ActivePersonaRequest):
    """Switch the active persona and reload agent personality state."""
    repo = _get_repo()
    await repo.init()
    async with _ACTIVE_PERSONA_SWITCH_LOCK:
        previous_id = await repo.get_active_id()
        previous_record = await repo.get(previous_id) if previous_id is not None else None
        try:
            record = await repo.get(payload.persona_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "personality.personas.errors.not_found",
                    language=_request_language(request),
                    fallback="Persona not found",
                ),
            )

        memory = None
        try:
            await repo.set_active(payload.persona_id)

            from ...personality.active_persona import set_current_personality
            from ...core.runtime_bindings import get_optional_agent_runtime
            from ...agent.runtime import TaskAgentType

            set_current_personality(record.slug, config=record.config)
            runtime = get_optional_agent_runtime()
            if runtime is not None:
                manager = runtime.get_task_agent_manager()
                chat_agent = await manager.ensure_agent(TaskAgentType.CHAT, "default")
                memory = getattr(chat_agent, "memory", None)
                if memory is None:
                    raise RuntimeError("Chat agent memory is unavailable")
                await memory.reload_personality(
                    record.slug,
                    personality_config=record.config,
                )
        except asyncio.CancelledError:
            await _restore_previous_persona_safely(repo, previous_record, memory)
            raise
        except Exception as exc:
            logger.warning("Failed to activate persona, restoring previous state: %s", exc)
            await _restore_previous_persona_safely(repo, previous_record, memory)
            raise HTTPException(
                status_code=503,
                detail=core_i18n.t(
                    "personality.personas.errors.activation_failed",
                    language=_request_language(request),
                    fallback="Failed to activate persona",
                ),
            ) from exc

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
async def create_persona(request: Request, payload: PersonaCreateRequest):
    """Create a new custom persona."""
    repo = _get_repo()
    await repo.init()
    try:
        json.loads(payload.config_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=core_i18n.t(
                "personality.personas.errors.invalid_config_json",
                language=_request_language(request),
                fallback="Invalid config_json",
            ),
        )
    persona_id = await repo.create(
        config_json=payload.config_json,
        locale=payload.locale,
        slug=payload.slug,
        persona_id=str(payload.persona_id) if payload.persona_id is not None else None,
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
            deleted_at=record.deleted_at,
        ),
    )


@personas_router.get("/{persona_id}", response_model=PersonaDetailResponse)
async def get_persona(request: Request, persona_id: str, include_deleted: bool = False):
    """Get full persona detail by ID."""
    repo = _get_repo()
    await repo.init()
    try:
        record = await repo.get(persona_id, include_deleted=include_deleted)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t(
                "personality.personas.errors.not_found",
                language=_request_language(request),
                fallback="Persona not found",
            ),
        )
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
            deleted_at=record.deleted_at,
        ),
    )


@personas_router.put("/{persona_id}", response_model=PersonaDetailResponse)
async def update_persona(request: Request, persona_id: str, payload: PersonaUpdateRequest):
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
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t(
                "personality.personas.errors.not_found",
                language=_request_language(request),
                fallback="Persona not found",
            ),
        )
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
            deleted_at=record.deleted_at,
        ),
    )


@personas_router.delete("/{persona_id}")
async def delete_persona(request: Request, persona_id: str):
    """Delete a persona (cannot delete the active one)."""
    repo = _get_repo()
    await repo.init()
    try:
        await repo.delete(persona_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t(
                "personality.personas.errors.not_found",
                language=_request_language(request),
                fallback="Persona not found",
            ),
        )
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail=core_i18n.t(
                "personality.personas.errors.cannot_delete_active",
                language=_request_language(request),
                fallback="Cannot delete the currently active persona",
            ),
        )
    return {"success": True}
