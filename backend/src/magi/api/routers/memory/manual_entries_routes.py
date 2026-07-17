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
from ....memory.manual_entries.locks import entry_mutation_lock as _entry_mutation_lock
from ....memory.manual_entries.workflow import (
    ManualEntryCleanupError,
    ManualEntryDeleteCompletionError,
    ManualEntryDeleteConflictError,
    ManualEntryDeleteStartError,
    ManualEntryDeletionInProgressError,
    ManualEntryNotFoundError,
    ManualEntryProjectionError,
    ManualEntryWorkflow,
    ManualEntryWorkflowError,
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


def _validate_attachment_refs(asset_store, attachment_refs: list[str]) -> None:
    """Reject forged or missing attachment references before persistence."""
    if all(asset_store.has_asset(asset_ref) for asset_ref in attachment_refs):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Attachment reference is invalid or unavailable",
    )


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
    projector = ManualEntryL1Projector(memory=unified) if l1 is not None else None
    weather = _resolve_manual_entry_weather_fetcher()
    location_samples = _resolve_location_sample_store()
    return store, assets, projector, weather, location_samples, unified


def _has_entry_changes(existing: ManualEntry, body: ManualEntryUpdateBody) -> bool:
    """Return whether the request changes user-authored entry state."""
    return any(
        (
            body.body is not None and body.body != existing.body,
            body.body_doc is not None and body.body_doc != existing.body_doc,
            body.clear_body_doc and existing.body_doc is not None,
            body.event_at is not None and float(body.event_at) != float(existing.event_at),
            body.mood is not None and (body.mood or None) != existing.mood,
            body.attachment_refs is not None
            and list(body.attachment_refs) != list(existing.attachments),
            body.user_pinned is not None and bool(body.user_pinned) != bool(existing.user_pinned),
            body.location_label is not None
            and (body.location_label or None) != existing.location_label,
        )
    )


def _has_projection_changes(existing: ManualEntry, body: ManualEntryUpdateBody) -> bool:
    """Return whether the update changes the canonical L1 projection."""
    return any(
        (
            body.body is not None and body.body != existing.body,
            body.event_at is not None and float(body.event_at) != float(existing.event_at),
            body.mood is not None and (body.mood or None) != existing.mood,
            body.attachment_refs is not None
            and list(body.attachment_refs) != list(existing.attachments),
            body.location_label is not None
            and (body.location_label or None) != existing.location_label,
        )
    )


def _memory_cleanup_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Memory cleanup did not complete; retry the request",
    )


def _memory_projection_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Memory projection did not complete; retry the request",
    )


def _deletion_in_progress_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="entry deletion is already in progress; retry the delete request",
    )


def _workflow_error(exc: ManualEntryWorkflowError) -> HTTPException:
    if isinstance(exc, ManualEntryCleanupError):
        return _memory_cleanup_error()
    if isinstance(exc, ManualEntryProjectionError):
        return _memory_projection_error()
    if isinstance(exc, ManualEntryDeletionInProgressError):
        return _deletion_in_progress_error()
    if isinstance(exc, ManualEntryNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="entry not found",
        )
    if isinstance(exc, ManualEntryDeleteStartError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manual entry deletion did not start; retry the request",
        )
    if isinstance(exc, ManualEntryDeleteCompletionError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manual entry deletion did not complete; retry the request",
        )
    if isinstance(exc, ManualEntryDeleteConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="entry changed while it was being deleted; retry the request",
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Manual entry operation did not complete; retry the request",
    )


async def _load_projection_state(store, entry_id: str) -> ManualEntry:
    try:
        return await ManualEntryWorkflow(
            store=store,
            projector=None,
            memory=None,
        ).load_projection_state(entry_id)
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


async def _forget_owned_projections(
    *,
    entry: ManualEntry,
    projector,
    memory,
    reason: str,
    block_source_item: bool,
) -> str | None:
    try:
        return await ManualEntryWorkflow(
            store=None,
            projector=projector,
            memory=memory,
        ).forget_owned_projections(
            entry=entry,
            reason=reason,
            block_source_item=block_source_item,
        )
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


async def _project_and_link(
    *,
    entry: ManualEntry,
    predecessor_event_id: str | None,
    store,
    projector,
    memory,
) -> None:
    try:
        await ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        ).project_and_link(
            entry=entry,
            predecessor_event_id=predecessor_event_id,
        )
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


async def _repair_projection_if_needed(
    *,
    entry: ManualEntry,
    store,
    projector,
    memory,
    reason: str,
) -> None:
    try:
        await ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        ).repair_projection_if_needed(
            entry=entry,
            reason=reason,
        )
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


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
        location_samples=location_samples,
        entry=entry,
    )
    if coords is None:
        return None
    lat, lng = coords
    try:
        weather = await weather_fetcher.fetch(
            lat=lat,
            lng=lng,
            event_at=entry.event_at,
        )
    except Exception:
        return None
    if not weather:
        return None
    try:
        persisted = await store.set_weather(entry.entry_id, weather)
    except Exception:
        return None
    if not persisted:
        return None
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
    _, asset_store, _, _, _, _ = _resolve_stores()
    return await store_uploaded_image_asset(file, asset_store)


# ─── Entry CRUD ──────────────────────────────────────────────────────


@memory_router.post("/manual-entries")
async def create_manual_entry(body: ManualEntryCreateBody):
    """Create a new entry and project it to L1.

    ``event_at`` defaults to ``time.time()`` when null — covers the
    common "writing about now" case without forcing the client to send
    a timestamp it just got from ``Date.now()``.
    """
    store, asset_store, projector, weather_fetcher, location_samples, memory = _resolve_stores()

    if not body.body.strip() and not body.attachment_refs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entry must have body text or at least one attachment",
        )
    _validate_attachment_refs(asset_store, body.attachment_refs)

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
    async with _entry_mutation_lock(entry.entry_id):
        try:
            await store.create(entry)
        except Exception as exc:
            # A connection can fail while reporting a commit that already
            # landed. Recover only this exact generated identity; otherwise
            # no projection is allowed to run.
            try:
                persisted = await store.get(entry.entry_id)
            except Exception as read_exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Manual entry storage did not complete; retry the request",
                ) from read_exc
            if (
                persisted is None
                or persisted.deleted_at is not None
                or persisted.created_at != entry.created_at
                or persisted.body != entry.body
            ):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Manual entry storage did not complete; retry the request",
                ) from exc
            entry = persisted

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

        await _project_and_link(
            entry=entry,
            predecessor_event_id=None,
            store=store,
            projector=projector,
            memory=memory,
        )

    return _entry_to_dict(entry)


@memory_router.get("/manual-entries")
async def list_manual_entries(
    time_start: float = Query(..., description="Unix sec, inclusive"),
    time_end: float = Query(..., description="Unix sec, inclusive"),
    limit: int = Query(default=500, ge=1, le=1000),
):
    store, _, _, _, _, _ = _resolve_stores()
    entries = await store.list_window(
        time_start=time_start,
        time_end=time_end,
        include_deleted=False,
        limit=limit,
    )
    return {"items": [_entry_to_dict(e) for e in entries]}


@memory_router.patch("/manual-entries/{entry_id}")
async def update_manual_entry(entry_id: str, body: ManualEntryUpdateBody):
    async with _entry_mutation_lock(entry_id):
        return await _update_manual_entry_locked(entry_id, body)


async def _update_manual_entry_locked(entry_id: str, body: ManualEntryUpdateBody):
    store, asset_store, projector, weather_fetcher, location_samples, memory = _resolve_stores()

    existing = await store.get(entry_id)
    if existing is None or existing.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="entry not found",
        )
    if existing.delete_requested_at is not None:
        raise _deletion_in_progress_error()

    if existing.pending_l1_event_id is not None:
        await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update_repair",
        )
        existing = await _load_projection_state(store, entry_id)
        if existing.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="entry not found",
            )
        if existing.delete_requested_at is not None:
            raise _deletion_in_progress_error()

    has_changes = _has_entry_changes(existing, body)
    if not has_changes:
        await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update",
        )
        return _entry_to_dict(existing)

    final_body = body.body if body.body is not None else existing.body
    final_attachments = (
        list(body.attachment_refs)
        if body.attachment_refs is not None
        else list(existing.attachments)
    )
    if not final_body.strip() and not final_attachments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entry must have body text or at least one attachment",
        )
    if body.attachment_refs is not None:
        _validate_attachment_refs(asset_store, final_attachments)

    projection_changed = _has_projection_changes(existing, body)
    predecessor_event_id = None
    if projection_changed:
        predecessor_event_id = await _forget_owned_projections(
            entry=existing,
            projector=projector,
            memory=memory,
            reason="manual_entry_update",
            block_source_item=False,
        )

    should_refresh_weather = (
        body.event_at is not None and abs(float(body.event_at) - float(existing.event_at)) >= 60.0
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
        clear_weather=should_refresh_weather,
        expected_l1_event_id=existing.l1_event_id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="entry changed while it was being updated; retry the request",
        )

    updated = await store.get(entry_id)
    # Re-fetch weather when event_at moved by more than a slop window —
    # the chip is keyed on (lat, lng, hour) and a non-trivial time shift
    # invalidates the snapshot. We wipe first so a failed re-fetch
    # doesn't leave the OLD weather hanging on a now-misleading time.
    if updated is not None and should_refresh_weather:
        await _attach_weather(
            weather_fetcher=weather_fetcher,
            location_samples=location_samples,
            store=store,
            entry=updated,
        )

    if updated is not None and projection_changed:
        await _project_and_link(
            entry=updated,
            predecessor_event_id=predecessor_event_id,
            store=store,
            projector=projector,
            memory=memory,
        )
    elif updated is not None:
        await _repair_projection_if_needed(
            entry=updated,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update",
        )

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
    async with _entry_mutation_lock(entry_id):
        return await _clear_manual_entry_weather_locked(entry_id)


async def _clear_manual_entry_weather_locked(entry_id: str):
    # NOTE: this route is mounted BEFORE the catch-all DELETE
    # /manual-entries/{entry_id} below — FastAPI registers paths in
    # decoration order, so the more-specific suffix has to win the
    # match. Keep them in this order.
    store, _, projector, _, _, memory = _resolve_stores()
    existing = await store.get(entry_id)
    if existing is None or existing.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="entry not found",
        )
    if existing.delete_requested_at is not None:
        raise _deletion_in_progress_error()
    if existing.pending_l1_event_id is not None:
        await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_weather_repair",
        )
        existing = await _load_projection_state(store, entry_id)
        if existing.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="entry not found",
            )
        if existing.delete_requested_at is not None:
            raise _deletion_in_progress_error()
    if existing.weather is None:
        await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_weather_clear",
        )
        return _entry_to_dict(existing)

    predecessor_event_id = await _forget_owned_projections(
        entry=existing,
        projector=projector,
        memory=memory,
        reason="manual_entry_weather_clear",
        block_source_item=False,
    )
    try:
        weather_cleared = await store.set_weather(entry_id, None)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manual entry update did not complete; retry the request",
        ) from exc
    if not weather_cleared:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="entry changed while it was being updated; retry the request",
        )
    existing.weather = None

    await _project_and_link(
        entry=existing,
        predecessor_event_id=predecessor_event_id,
        store=store,
        projector=projector,
        memory=memory,
    )

    return _entry_to_dict(existing)


@memory_router.delete("/manual-entries/{entry_id}")
async def delete_manual_entry(entry_id: str):
    async with _entry_mutation_lock(entry_id):
        return await _delete_manual_entry_locked(entry_id)


async def _delete_manual_entry_locked(entry_id: str):
    store, _, projector, _, _, memory = _resolve_stores()
    try:
        result = await ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        ).delete_entry(
            entry_id,
        )
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc
    if result.already_deleted:
        return {"ok": True, "already_deleted": True}
    return {"ok": True}
