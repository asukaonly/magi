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
from .asset_uploads import store_uploaded_image_asset
from .dependencies import (
    _resolve_location_sample_store,
    _resolve_manual_entry_asset_store,
    _resolve_manual_entry_store,
    _resolve_manual_entry_weather_fetcher,
    _resolve_unified_memory,
)
from .router import memory_router


# ─── Request / response shapes ───────────────────────────────────────


class ManualEntryCreateBody(BaseModel):
    body: str
    # Optional ProseMirror JSON document for the rich-text editor
    # (Phase B-2). The plain `body` field is still required — it's the
    # canonical text projection consumed by L1, search, and the diary
    # LLM. Clients send both, derived from the same editor state.
    body_doc: Optional[dict] = None
    event_at: Optional[float] = None
    mood: Optional[str] = None
    location_label: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    attachment_refs: list[str] = Field(default_factory=list)


class ManualEntryUpdateBody(BaseModel):
    body: Optional[str] = None
    body_doc: Optional[dict] = None
    # Explicit flag for clearing body_doc — there's no natural "empty"
    # JSON dict so we can't reuse the empty-string-clears convention.
    clear_body_doc: bool = False
    event_at: Optional[float] = None
    mood: Optional[str] = None
    attachment_refs: Optional[list[str]] = None
    user_pinned: Optional[bool] = None
    # Text fields use the empty-string-clears convention: omit (=None)
    # means "don't touch"; "" means "clear to NULL"; other strings set.
    # This lets the UI's ✕ buttons persist without needing a separate
    # delete-this-field endpoint per attribute.
    location_label: Optional[str] = None


def _entry_to_dict(entry: ManualEntry) -> dict:
    return entry.to_dict()


def _resolve_stores():
    """Resolve the manual-entry components from their DI bindings.

    The store/asset/weather subsystem is owned by ``ManualEntriesModule``; the
    L1 projector is built from the memory-owned L1 store (memory's only stake).
    Raises 503 if the manual-entry storage is missing so callers see a clear
    message rather than an internal NoneType error.

    Returns ``(store, assets, projector, weather, location_samples)``.
    ``weather`` and ``location_samples`` are best-effort — None when the
    subsystem isn't wired and the routes degrade gracefully.
    """
    store = _resolve_manual_entry_store()
    assets = _resolve_manual_entry_asset_store()
    if store is None or assets is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manual-entry storage not initialized",
        )
    # Memory's only stake in manual entries is the L1 projection: build the
    # projector from the memory-owned L1 store (best-effort — the routes
    # degrade gracefully if memory is absent).
    unified = _resolve_unified_memory()
    l1 = getattr(unified, "l1", None) if unified is not None else None
    projector = ManualEntryL1Projector(l1_store=l1) if l1 is not None else None
    weather = _resolve_manual_entry_weather_fetcher()
    location_samples = _resolve_location_sample_store()
    return store, assets, projector, weather, location_samples


async def _resolve_weather_coords(
    *,
    location_samples,
    entry,
) -> Optional[tuple[float, float]]:
    """Return (lat, lng) for the weather lookup, or None if unresolvable.

    Priority:
      1. The entry's own ``location_lat / location_lng`` (frontend may pass
         these if the user picked a place with attached coords).
      2. The most recent location sample at or before ``event_at`` — even
         if the user typed the label by hand, the ambient location is a
         strict-improvement over nothing.
    """
    if entry.location_lat is not None and entry.location_lng is not None:
        return float(entry.location_lat), float(entry.location_lng)
    if location_samples is None:
        return None
    try:
        sample = await location_samples.latest(before=entry.event_at)
    except Exception:
        return None
    if sample is None or sample.lat is None or sample.lng is None:
        return None
    return float(sample.lat), float(sample.lng)


async def _attach_weather(
    *,
    weather_fetcher,
    location_samples,
    store,
    entry,
) -> Optional[dict]:
    """Best-effort: fetch weather and persist it onto the entry.

    Returns the weather dict on success (also mutates entry in-place so
    callers can hand it straight to the L1 projector); None on any
    failure path. Never raises — weather is decorative.
    """
    if weather_fetcher is None:
        return None
    coords = await _resolve_weather_coords(
        location_samples=location_samples, entry=entry,
    )
    if coords is None:
        return None
    lat, lng = coords
    try:
        weather = await weather_fetcher.fetch(
            lat=lat, lng=lng, event_at=entry.event_at,
        )
    except Exception:
        return None
    if not weather:
        return None
    try:
        await store.set_weather(entry.entry_id, weather)
    except Exception:
        # The fetch succeeded but persisting didn't — still return the
        # value so the response carries it; next user-driven update will
        # re-persist.
        pass
    entry.weather = weather
    return weather


# ─── Asset upload ────────────────────────────────────────────────────


@memory_router.post("/manual-entries/assets")
async def upload_manual_entry_asset(file: UploadFile):
    """Upload a single image attachment.

    Returns ``{asset_ref, content_type, byte_size}``. The caller then
    includes the asset_ref in a subsequent ``POST /manual-entries`` body.
    Storage is content-addressed (sha256) so repeated uploads of the
    same bytes resolve to a single file on disk + a single ref.
    """
    _, asset_store, _, _, _ = _resolve_stores()
    return await store_uploaded_image_asset(file, asset_store)


# ─── Entry CRUD ──────────────────────────────────────────────────────


@memory_router.post("/manual-entries")
async def create_manual_entry(body: ManualEntryCreateBody):
    """Create a new entry and project it to L1.

    ``event_at`` defaults to ``time.time()`` when null — covers the
    common "writing about now" case without forcing the client to send
    a timestamp it just got from ``Date.now()``.
    """
    store, _, projector, weather_fetcher, location_samples = _resolve_stores()

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
        body_doc=body.body_doc,
        mood=body.mood or None,
        location_label=body.location_label or None,
        location_lat=body.location_lat,
        location_lng=body.location_lng,
        attachments=list(body.attachment_refs),
    )
    await store.create(entry)

    # Attach ambient weather BEFORE L1 projection so the weather lands
    # in the metadata blob. Inline (not background) because the response
    # then includes the chip data — the timeline refresh after save
    # immediately renders it. Failure is silent.
    await _attach_weather(
        weather_fetcher=weather_fetcher,
        location_samples=location_samples,
        store=store,
        entry=entry,
    )

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
    store, _, _, _, _ = _resolve_stores()
    entries = await store.list_window(
        time_start=time_start,
        time_end=time_end,
        include_deleted=include_deleted,
        limit=limit,
    )
    return {"items": [_entry_to_dict(e) for e in entries]}


@memory_router.patch("/manual-entries/{entry_id}")
async def update_manual_entry(entry_id: str, body: ManualEntryUpdateBody):
    store, _, projector, weather_fetcher, location_samples = _resolve_stores()

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
        location_label=body.location_label,
        body_doc=body.body_doc,
        clear_body_doc=body.clear_body_doc,
    )
    if not ok:
        # No fields actually changed — return current state, not an error.
        return _entry_to_dict(existing)

    updated = await store.get(entry_id)
    # Re-fetch weather when event_at moved by more than a slop window —
    # the chip is keyed on (lat, lng, hour) and a non-trivial time shift
    # invalidates the snapshot. We wipe first so a failed re-fetch
    # doesn't leave the OLD weather hanging on a now-misleading time.
    if (
        updated is not None
        and body.event_at is not None
        and abs(float(body.event_at) - existing.event_at) >= 60.0
    ):
        await store.set_weather(entry_id, None)
        updated.weather = None
        await _attach_weather(
            weather_fetcher=weather_fetcher,
            location_samples=location_samples,
            store=store,
            entry=updated,
        )

    if projector is not None and updated is not None:
        try:
            new_l1_event_id = await projector.project_on_update(updated)
            await store.link_l1_event(entry_id, new_l1_event_id)
            updated.l1_event_id = new_l1_event_id
        except Exception:
            pass

    return _entry_to_dict(updated or existing)


@memory_router.delete("/manual-entries/{entry_id}/weather")
async def clear_manual_entry_weather(entry_id: str):
    """Drop the auto-resolved weather snapshot.

    Reached via the ✕ button on the chip in the QuickEntrySheet. We
    don't allow setting weather from the client — only clearing —
    because user-supplied weather isn't meaningfully better than no
    chip, and accepting writes would invite garbage data.

    Re-projects to L1 so downstream consumers see the absence too.
    """
    # NOTE: this route is mounted BEFORE the catch-all DELETE
    # /manual-entries/{entry_id} below — FastAPI registers paths in
    # decoration order, so the more-specific suffix has to win the
    # match. Keep them in this order.
    store, _, projector, _, _ = _resolve_stores()
    existing = await store.get(entry_id)
    if existing is None or existing.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="entry not found",
        )
    if existing.weather is None:
        # Idempotent: no-op when there's nothing to clear.
        return _entry_to_dict(existing)

    await store.set_weather(entry_id, None)
    existing.weather = None

    # Re-project so the L1 metadata's `weather` field also becomes null.
    # Failure mode is the same as elsewhere: log via the surrounding
    # exception handler and move on — the user-facing clear succeeded.
    if projector is not None:
        try:
            new_l1_event_id = await projector.project_on_update(existing)
            await store.link_l1_event(entry_id, new_l1_event_id)
            existing.l1_event_id = new_l1_event_id
        except Exception:
            pass

    return _entry_to_dict(existing)


@memory_router.delete("/manual-entries/{entry_id}")
async def delete_manual_entry(entry_id: str):
    store, _, projector, _, _ = _resolve_stores()
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
