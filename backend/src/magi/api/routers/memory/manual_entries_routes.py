"""HTTP validation and response contracts for manual-entry application services."""

from __future__ import annotations
from fastapi import HTTPException, Query, UploadFile, status
from magi.memory.manual_entries import ManualEntryL1Projector
from magi.memory.manual_entries import application
from magi.memory.manual_entries.commands import (
    ManualEntryCreateBody,
    ManualEntryUpdateBody,
    ManualEntryCreateResponse,
)
from magi.api.services.memory_application import memory_application_result
from .asset_uploads import store_uploaded_image_asset
from . import dependencies
from .router import memory_router


def _resolve_stores():
    """Resolve the manual-entry components from their DI bindings.

    The store/asset/weather subsystem is owned by ``ManualEntriesModule``; the
    L1 projector is built from the memory-owned L1 store (memory's only stake).
    Raises 503 if the manual-entry storage is missing so callers see a clear
    message rather than an internal NoneType error.

    Returns ``(store, assets, projector, weather, location_samples, memory)``.
    ``weather`` and ``location_samples`` are best-effort — None when the
    subsystem isn't wired and the routes degrade gracefully.
    """
    store = dependencies._resolve_manual_entry_store()
    assets = dependencies._resolve_manual_entry_asset_store()
    if store is None or assets is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manual-entry storage not initialized",
        )
    # Memory's only stake in manual entries is the L1 projection: build the
    # projector from the memory-owned L1 store (best-effort — the routes
    # degrade gracefully if memory is absent).
    unified = dependencies._resolve_unified_memory()
    l1 = getattr(unified, "l1", None) if unified is not None else None
    projector = ManualEntryL1Projector(memory=unified) if l1 is not None else None
    weather = dependencies._resolve_manual_entry_weather_fetcher()
    location_samples = dependencies._resolve_location_sample_store()
    return store, assets, projector, weather, location_samples, unified


def _resolve_service() -> application.ManualEntryDependencies:
    return application.ManualEntryDependencies(*_resolve_stores())


@memory_router.post("/manual-entries/assets")
async def upload_manual_entry_asset(file: UploadFile):
    services = _resolve_service()
    return await memory_application_result(
        application.upload_manual_entry_asset(
            lambda: store_uploaded_image_asset(file, services.assets), services=services
        )
    )


@memory_router.post("/manual-entries", response_model=ManualEntryCreateResponse)
async def create_manual_entry(body: ManualEntryCreateBody):
    return await memory_application_result(
        application.create_manual_entry(body=body, services=_resolve_service())
    )


@memory_router.get("/manual-entries")
async def list_manual_entries(
    time_start: float = Query(..., description="Unix sec, inclusive"),
    time_end: float = Query(..., description="Unix sec, inclusive"),
    limit: int = Query(default=500, ge=1, le=1000),
):
    return await memory_application_result(
        application.list_manual_entries(
            time_start=time_start, time_end=time_end, limit=limit, services=_resolve_service()
        )
    )


@memory_router.get("/manual-entries/{entry_id}")
async def get_manual_entry(entry_id: str):
    return await memory_application_result(
        application.get_manual_entry(entry_id=entry_id, services=_resolve_service())
    )


@memory_router.patch("/manual-entries/{entry_id}")
async def update_manual_entry(entry_id: str, body: ManualEntryUpdateBody):
    return await memory_application_result(
        application.update_manual_entry(entry_id=entry_id, body=body, services=_resolve_service())
    )


@memory_router.delete("/manual-entries/{entry_id}/weather")
async def clear_manual_entry_weather(entry_id: str):
    return await memory_application_result(
        application.clear_manual_entry_weather(entry_id=entry_id, services=_resolve_service())
    )


@memory_router.delete("/manual-entries/{entry_id}")
async def delete_manual_entry(entry_id: str):
    return await memory_application_result(
        application.delete_manual_entry(entry_id=entry_id, services=_resolve_service())
    )
