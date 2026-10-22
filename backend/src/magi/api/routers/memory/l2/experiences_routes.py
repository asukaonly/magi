"""HTTP contracts and asset adapters for experience application workflows."""

from __future__ import annotations

from typing import Any

from fastapi import Form, Query, UploadFile

from magi.api.services.memory_application import memory_application_result
from magi.memory.l2.experiences import application
from magi.memory.l2.experiences.commands import (
    ExperienceAnnotationRequest,
    ExperienceDraftOrganizeRequest,
    ExperienceDraftUpdateRequest,
    ExperienceSeedCreateRequest,
)

from .. import dependencies
from ..asset_uploads import store_uploaded_image_asset
from ..router import memory_router


def _image_upload(file: UploadFile):
    assets = dependencies._resolve_manual_entry_asset_store()
    return (lambda: store_uploaded_image_asset(file, assets)) if assets is not None else None


@memory_router.post("/l2/experience-drafts/organize")
async def organize_experience_draft_route(body: ExperienceDraftOrganizeRequest) -> dict[str, Any]:
    return await memory_application_result(
        application.organize_draft(
            body=body, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.get("/l2/experience-drafts")
async def list_experience_drafts_route(
    draft_status: str = Query(default="editing", alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await memory_application_result(
        application.list_drafts(
            draft_status=draft_status,
            limit=limit,
            offset=offset,
            memory=dependencies._resolve_unified_memory(),
        )
    )


@memory_router.get("/l2/experience-drafts/{draft_id}")
async def get_experience_draft_route(draft_id: str) -> dict[str, Any]:
    return await memory_application_result(
        application.get_draft(
            draft_id=draft_id, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.patch("/l2/experience-drafts/{draft_id}")
async def update_experience_draft_route(
    draft_id: str, body: ExperienceDraftUpdateRequest
) -> dict[str, Any]:
    return await memory_application_result(
        application.update_draft(
            draft_id=draft_id, body=body, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.post("/l2/experience-drafts/{draft_id}/cover")
async def upload_experience_draft_cover(
    draft_id: str,
    file: UploadFile,
    expected_updated_at: float | None = Query(default=None, ge=0, allow_inf_nan=False),
) -> dict[str, Any]:
    return await memory_application_result(
        application.set_draft_cover(
            draft_id=draft_id,
            expected_updated_at=expected_updated_at,
            upload_image=_image_upload(file),
            memory=dependencies._resolve_unified_memory(),
        )
    )


@memory_router.post("/l2/experience-drafts/{draft_id}/create")
async def create_experience_from_draft_route(
    draft_id: str,
    expected_updated_at: float | None = Query(default=None, ge=0, allow_inf_nan=False),
) -> dict[str, Any]:
    return await memory_application_result(
        application.create_from_draft(
            draft_id=draft_id,
            expected_updated_at=expected_updated_at,
            memory=dependencies._resolve_unified_memory(),
        )
    )


@memory_router.post("/l2/experience-seeds")
async def create_l2_experience_seed(body: ExperienceSeedCreateRequest) -> dict[str, Any]:
    return await memory_application_result(
        application.create_seed(
            body=body, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.get("/l2/experience-seeds")
async def list_l2_experience_seeds(
    status_filter: str | None = Query(default="candidate", alias="status"),
    limit: int = Query(default=12, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await memory_application_result(
        application.list_seeds(
            status_filter=status_filter,
            limit=limit,
            offset=offset,
            memory=dependencies._resolve_unified_memory(),
        )
    )


@memory_router.post("/l2/experience-seeds/{seed_id}/promote")
async def promote_l2_experience_seed(seed_id: str) -> dict[str, Any]:
    return await memory_application_result(
        application.promote_seed(
            seed_id=seed_id, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.post("/l2/experience-seeds/{seed_id}/reject")
async def reject_l2_experience_seed(seed_id: str) -> dict[str, Any]:
    return await memory_application_result(
        application.reject_seed(
            seed_id=seed_id, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.get("/l2/experiences")
async def list_l2_experiences(
    status_filter: str | None = Query(default=None, alias="status"),
    time_start: float | None = Query(default=None),
    time_end: float | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await memory_application_result(
        application.list_experiences(
            status_filter=status_filter,
            time_start=time_start,
            time_end=time_end,
            limit=limit,
            offset=offset,
            memory=dependencies._resolve_unified_memory(),
        )
    )


@memory_router.get("/l2/experiences/{experience_id}")
async def get_l2_experience(experience_id: str) -> dict[str, Any]:
    return await memory_application_result(
        application.get_experience(
            experience_id=experience_id, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.post("/l2/experiences/{experience_id}/cover")
async def upload_l2_experience_cover(
    experience_id: str, file: UploadFile, expected_revision: str | None = Form(None)
) -> dict[str, Any]:
    return await memory_application_result(
        application.set_experience_cover(
            experience_id=experience_id,
            expected_revision=expected_revision,
            upload_image=_image_upload(file),
            memory=dependencies._resolve_unified_memory(),
        )
    )


@memory_router.patch("/l2/experiences/{experience_id}")
async def annotate_l2_experience(
    experience_id: str, body: ExperienceAnnotationRequest
) -> dict[str, Any]:
    return await memory_application_result(
        application.annotate_experience(
            experience_id=experience_id, body=body, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.post("/l2/experiences/{experience_id}/hide")
async def hide_l2_experience(experience_id: str) -> dict[str, Any]:
    return await memory_application_result(
        application.hide_experience(
            experience_id=experience_id, memory=dependencies._resolve_unified_memory()
        )
    )


@memory_router.post("/l2/experiences/{experience_id}/regenerate")
async def regenerate_l2_experience(experience_id: str) -> dict[str, Any]:
    return await memory_application_result(
        application.regenerate_experience(
            experience_id=experience_id, memory=dependencies._resolve_unified_memory()
        )
    )
