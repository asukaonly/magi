"""HTTP routes for user-authored memory entries.

Mounted under ``/api/memory/manual-entries``. The companion
``/api/memory/manual-entries/assets`` endpoint accepts image uploads
(multipart) and returns a content-addressed asset_ref the caller then
includes in the entry's ``attachment_refs`` list.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from ....memory.manual_entries import (
    ManualEntry,
    ManualEntryL1Projector,
)
from ....memory.manual_entries.asset_store import (
    ACCEPTED_CONTENT_TYPES,
    KNOWN_UNSUPPORTED_CONTENT_TYPES,
    MAX_UPLOAD_BYTES,
)
from .dependencies import _resolve_unified_memory
from .router import memory_router


# ─── Request / response shapes ───────────────────────────────────────


class ManualEntryCreateBody(BaseModel):
    body: str
    event_at: Optional[float] = None
    mood: Optional[str] = None
    location_label: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    attachment_refs: list[str] = Field(default_factory=list)


class ManualEntryUpdateBody(BaseModel):
    body: Optional[str] = None
    event_at: Optional[float] = None
    mood: Optional[str] = None
    attachment_refs: Optional[list[str]] = None
    user_pinned: Optional[bool] = None


def _entry_to_dict(entry: ManualEntry) -> dict:
    return entry.to_dict()


def _resolve_stores():
    """Pull the manual-entry components off unified_memory.

    Raises 503 if anything is missing so callers see a clear message
    rather than an internal NoneType error.
    """
    unified = _resolve_unified_memory()
    if unified is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory subsystem not available",
        )
    store = getattr(unified, "manual_entry_store", None)
    assets = getattr(unified, "manual_entry_asset_store", None)
    l1 = getattr(unified, "l1", None)
    if store is None or assets is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manual-entry storage not initialized",
        )
    projector = ManualEntryL1Projector(l1_store=l1) if l1 is not None else None
    return store, assets, projector


# ─── Asset upload ────────────────────────────────────────────────────


@memory_router.post("/manual-entries/assets")
async def upload_manual_entry_asset(file: UploadFile):
    """Upload a single image attachment.

    Returns ``{asset_ref, content_type, byte_size}``. The caller then
    includes the asset_ref in a subsequent ``POST /manual-entries`` body.
    Storage is content-addressed (sha256) so repeated uploads of the
    same bytes resolve to a single file on disk + a single ref.
    """
    _, asset_store, _ = _resolve_stores()

    content_type = (file.content_type or "").lower()
    if content_type in KNOWN_UNSUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=KNOWN_UNSUPPORTED_CONTENT_TYPES[content_type],
        )
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"图片格式不支持: {content_type or 'unknown'}",
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"图片超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty upload",
        )

    asset_ref = asset_store.store_bytes(data, content_type=content_type)
    return {
        "asset_ref": asset_ref,
        "content_type": content_type,
        "byte_size": len(data),
    }


# ─── Entry CRUD ──────────────────────────────────────────────────────


@memory_router.post("/manual-entries")
async def create_manual_entry(body: ManualEntryCreateBody):
    """Create a new entry and project it to L1.

    ``event_at`` defaults to ``time.time()`` when null — covers the
    common "writing about now" case without forcing the client to send
    a timestamp it just got from ``Date.now()``.
    """
    store, _, projector = _resolve_stores()

    if not body.body.strip() and not body.attachment_refs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entry must have body text or at least one attachment",
        )

    now = time.time()
    entry = ManualEntry(
        entry_id=f"me-{uuid.uuid4().hex[:12]}",
        created_at=now,
        event_at=float(body.event_at) if body.event_at is not None else now,
        kind="quick",
        body=body.body,
        mood=body.mood or None,
        location_label=body.location_label or None,
        location_lat=body.location_lat,
        location_lng=body.location_lng,
        attachments=list(body.attachment_refs),
    )
    await store.create(entry)

    if projector is not None:
        try:
            l1_event_id = await projector.project_on_create(entry)
            entry.l1_event_id = l1_event_id
            await store.link_l1_event(entry.entry_id, l1_event_id)
        except Exception:
            # L1 projection failure shouldn't drop the user's data —
            # the entry itself is already in manual_entries. Surface as
            # a soft warning; a future periodic projector can backfill.
            pass

    return _entry_to_dict(entry)


@memory_router.get("/manual-entries")
async def list_manual_entries(
    time_start: float = Query(..., description="Unix sec, inclusive"),
    time_end: float = Query(..., description="Unix sec, inclusive"),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=1000),
):
    store, _, _ = _resolve_stores()
    entries = await store.list_window(
        time_start=time_start,
        time_end=time_end,
        include_deleted=include_deleted,
        limit=limit,
    )
    return {"items": [_entry_to_dict(e) for e in entries]}


@memory_router.patch("/manual-entries/{entry_id}")
async def update_manual_entry(entry_id: str, body: ManualEntryUpdateBody):
    store, _, projector = _resolve_stores()

    existing = await store.get(entry_id)
    if existing is None or existing.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="entry not found",
        )

    ok = await store.update(
        entry_id,
        body=body.body,
        mood=body.mood if body.mood is not None else None,
        event_at=body.event_at,
        attachments=body.attachment_refs,
        user_pinned=body.user_pinned,
    )
    if not ok:
        # No fields actually changed — return current state, not an error.
        return _entry_to_dict(existing)

    updated = await store.get(entry_id)
    if projector is not None and updated is not None:
        try:
            new_l1_event_id = await projector.project_on_update(updated)
            await store.link_l1_event(entry_id, new_l1_event_id)
            updated.l1_event_id = new_l1_event_id
        except Exception:
            pass

    return _entry_to_dict(updated or existing)


@memory_router.delete("/manual-entries/{entry_id}")
async def delete_manual_entry(entry_id: str):
    store, _, projector = _resolve_stores()
    existing = await store.get(entry_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="entry not found",
        )
    if existing.deleted_at is not None:
        return {"ok": True, "already_deleted": True}

    await store.soft_delete(entry_id)
    if projector is not None:
        try:
            await projector.project_on_delete(existing)
        except Exception:
            pass

    return {"ok": True}
