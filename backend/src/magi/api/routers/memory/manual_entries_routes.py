"""HTTP routes for user-authored memory entries.

Mounted under ``/api/memory/manual-entries``. The companion
``/api/memory/manual-entries/assets`` endpoint accepts image uploads
(multipart) and returns a content-addressed asset_ref the caller then
includes in the entry's ``attachment_refs`` list.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Literal, Optional

from fastapi import HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from ....core.logger import get_logger
from ....memory.manual_entries import (
    ManualEntry,
    ManualEntryL1Projector,
)
from ....memory.manual_entries.l1_projector import (
    ManualEntryProjectionGovernedError,
)
from ....memory.manual_entries.locks import entry_mutation_lock as _entry_mutation_lock
from ....memory.manual_entries.workflow import (
    ManualEntryCleanupError,
    ManualEntryDeleteCompletionError,
    ManualEntryDeleteConflictError,
    ManualEntryDeleteStartError,
    ManualEntryDeletionInProgressError,
    ManualEntryGovernanceRejectedError,
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

logger = get_logger(__name__)

# ─── Request / response shapes ───────────────────────────────────────


class ManualEntryCreateBody(BaseModel):
    entry_id: str = Field(
        min_length=4,
        max_length=131,
        pattern=r"^me-[A-Za-z0-9][A-Za-z0-9-]*$",
    )
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


class ManualEntryCreateResponse(BaseModel):
    """Public entry plus the readiness of its derived memory."""

    entry_id: str
    created_at: float
    event_at: float
    kind: str
    body: str
    body_doc: Optional[dict[str, Any]] = None
    mood: Optional[str] = None
    location_label: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    attachments: list[str]
    exclude_from_llm: bool
    user_pinned: bool
    deleted_at: Optional[float] = None
    l1_event_id: Optional[str] = None
    weather: Optional[dict[str, Any]] = None
    memory_status: Literal["ready", "pending"]


def _entry_to_dict(entry: ManualEntry) -> dict:
    return entry.to_dict()


def _create_response(
    entry: ManualEntry,
    *,
    projection_unconfirmed: bool,
) -> dict:
    result = _entry_to_dict(entry)
    result["memory_status"] = (
        "pending"
        if projection_unconfirmed
        or entry.l1_event_id is None
        or entry.pending_l1_event_id is not None
        else "ready"
    )
    return result


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


def _memory_forgotten_error(
    *,
    reason: str,
    source_preserved: bool = False,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "manual_entry_memory_forgotten",
            "reason": str(reason or "source_reference"),
            "retry_as_new": not source_preserved,
            "source_preserved": source_preserved,
            "message": (
                "This occurrence is covered by a durable memory-forget rule"
            ),
        },
    )


def _deletion_in_progress_error() -> HTTPException:
    return _memory_forgotten_error(reason="source_reference")


def _workflow_error(exc: ManualEntryWorkflowError) -> HTTPException:
    if isinstance(exc, ManualEntryGovernanceRejectedError):
        return _memory_forgotten_error(
            reason=exc.reason,
            source_preserved=exc.source_preserved,
        )
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


async def _replace_and_project(
    *,
    entry: ManualEntry,
    predecessor_event_id: str | None,
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
        ).replace_and_project(
            entry=entry,
            predecessor_event_id=predecessor_event_id,
            reason=reason,
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
) -> bool:
    try:
        return await ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        ).repair_projection_if_needed(
            entry=entry,
            reason=reason,
        )
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


def _create_request_matches(
    existing: ManualEntry,
    body: ManualEntryCreateBody,
) -> bool:
    """Compare only user-controlled create fields for idempotent retries."""
    return bool(
        existing.kind == "quick"
        and existing.body == body.body
        and existing.body_doc == body.body_doc
        and (
            body.event_at is None
            or float(existing.event_at) == float(body.event_at)
        )
        and existing.mood == (body.mood or None)
        and existing.location_label == (body.location_label or None)
        and existing.location_lat == body.location_lat
        and existing.location_lng == body.location_lng
        and list(existing.attachments) == list(body.attachment_refs)
    )


def _create_identity_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="entry identity is already used by different content",
    )


async def _terminal_source_conflict(
    *,
    projector,
    entry: ManualEntry,
    predecessor_event_id: str | None = None,
) -> HTTPException:
    """Describe a terminal source identity with its current governance rule."""
    reason = "source_reference"
    if projector is not None:
        try:
            await projector.ensure_projectable(
                entry,
                predecessor_event_id=predecessor_event_id,
            )
        except ManualEntryProjectionGovernedError as exc:
            reason = exc.reason
        except Exception:
            # The source row is already terminal. A transient governance read
            # must not downgrade that fact to an ordinary identity conflict.
            pass
    return _memory_forgotten_error(reason=reason)


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
    weather = await _fetch_weather(
        weather_fetcher=weather_fetcher,
        location_samples=location_samples,
        entry=entry,
    )
    if weather is None:
        return None
    try:
        persisted = await store.set_weather(entry.entry_id, weather)
    except Exception:
        # The database may have committed before the caller lost the
        # acknowledgement. Reload the exact source so L1 and the response use
        # the confirmed snapshot instead of projecting the stale object.
        try:
            confirmed = await store.get(entry.entry_id)
        except Exception:
            return None
        if (
            confirmed is None
            or confirmed.deleted_at is not None
            or confirmed.weather != weather
        ):
            return None
        entry.weather = dict(confirmed.weather)
        return entry.weather
    if not persisted:
        return None
    entry.weather = weather
    return weather


async def _fetch_weather(
    *,
    weather_fetcher,
    location_samples,
    entry,
) -> Optional[dict]:
    """Resolve weather without mutating the source row."""
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
    return weather or None


def _apply_entry_update(
    existing: ManualEntry,
    body: ManualEntryUpdateBody,
) -> ManualEntry:
    """Build the complete source snapshot represented by a partial update."""
    updated = replace(existing)
    if body.body is not None:
        updated.body = body.body
    if body.body_doc is not None:
        updated.body_doc = dict(body.body_doc)
    elif body.clear_body_doc:
        updated.body_doc = None
    if body.event_at is not None:
        updated.event_at = float(body.event_at)
    if body.mood is not None:
        updated.mood = body.mood or None
    if body.attachment_refs is not None:
        updated.attachments = list(body.attachment_refs)
    if body.user_pinned is not None:
        updated.user_pinned = bool(body.user_pinned)
    if body.location_label is not None:
        updated.location_label = body.location_label or None
    return updated


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


@memory_router.post(
    "/manual-entries",
    response_model=ManualEntryCreateResponse,
)
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

    async with _entry_mutation_lock(body.entry_id):
        try:
            existing = await store.get(body.entry_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Manual entry storage did not complete; retry the request",
            ) from exc
        if existing is not None:
            if (
                existing.deleted_at is not None
                or existing.delete_requested_at is not None
            ):
                raise await _terminal_source_conflict(
                    projector=projector,
                    entry=existing,
                )
            if not _create_request_matches(existing, body):
                raise _create_identity_conflict()
            entry = existing
        else:
            now = time.time()
            entry = ManualEntry(
                entry_id=body.entry_id,
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
            if projector is not None:
                try:
                    await projector.ensure_projectable(
                        entry,
                        predecessor_event_id=None,
                    )
                except ManualEntryProjectionGovernedError as exc:
                    raise _memory_forgotten_error(
                        reason=exc.reason,
                    ) from exc
                except Exception as exc:
                    raise _memory_projection_error() from exc
        try:
            if existing is None:
                await store.create(entry)
        except Exception as exc:
            try:
                persisted = await store.get(entry.entry_id)
            except Exception as read_exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Manual entry storage did not complete; retry the request",
                ) from read_exc
            if persisted is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Manual entry storage did not complete; retry the request",
                ) from exc
            if (
                persisted.deleted_at is not None
                or persisted.delete_requested_at is not None
            ):
                raise await _terminal_source_conflict(
                    projector=projector,
                    entry=persisted,
                ) from exc
            if not _create_request_matches(persisted, body):
                raise _create_identity_conflict() from exc
            entry = persisted

        if (
            entry.l1_event_id is None
            and entry.pending_l1_event_id is None
            and entry.weather is None
        ):
            # Service-owned weather is deliberately outside retry equality.
            # A repeated request resumes the same source even if this
            # best-effort enrichment landed during the first attempt.
            await _attach_weather(
                weather_fetcher=weather_fetcher,
                location_samples=location_samples,
                store=store,
                entry=entry,
            )

        projection_unconfirmed = False
        try:
            await _repair_projection_if_needed(
                entry=entry,
                store=store,
                projector=projector,
                memory=memory,
                reason="manual_entry_create",
            )
        except HTTPException as exc:
            if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
                raise
            # The user-owned source row is already durable. Treat derived
            # memory as delayed work instead of making the user save again.
            projection_unconfirmed = True
            logger.warning(
                "Manual-entry projection deferred after source save",
                entry_id=entry.entry_id,
                error=exc.detail,
            )
        try:
            persisted = await _load_projection_state(store, entry.entry_id)
        except HTTPException:
            if not projection_unconfirmed:
                raise
        else:
            if (
                persisted.deleted_at is not None
                or persisted.delete_requested_at is not None
            ):
                raise await _terminal_source_conflict(
                    projector=projector,
                    entry=persisted,
                )
            entry = persisted

    return _create_response(
        entry,
        projection_unconfirmed=projection_unconfirmed,
    )


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
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="entry not found",
        )
    if (
        existing.deleted_at is not None
        or existing.delete_requested_at is not None
    ):
        raise await _terminal_source_conflict(
            projector=projector,
            entry=existing,
            predecessor_event_id=existing.l1_event_id,
        )

    if existing.pending_l1_event_id is not None:
        await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update_repair",
        )
        existing = await _load_projection_state(store, entry_id)
        if (
            existing.deleted_at is not None
            or existing.delete_requested_at is not None
        ):
            raise await _terminal_source_conflict(
                projector=projector,
                entry=existing,
                predecessor_event_id=existing.l1_event_id,
            )

    has_changes = _has_entry_changes(existing, body)
    if not has_changes:
        repaired = await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update",
        )
        if repaired:
            existing = await _load_projection_state(store, entry_id)
            if (
                existing.deleted_at is not None
                or existing.delete_requested_at is not None
            ):
                raise await _terminal_source_conflict(
                    projector=projector,
                    entry=existing,
                    predecessor_event_id=existing.l1_event_id,
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
    should_refresh_weather = (
        body.event_at is not None and abs(float(body.event_at) - float(existing.event_at)) >= 60.0
    )
    candidate = _apply_entry_update(existing, body)
    if should_refresh_weather:
        candidate.weather = await _fetch_weather(
            weather_fetcher=weather_fetcher,
            location_samples=location_samples,
            entry=candidate,
        )

    if projection_changed:
        await _replace_and_project(
            entry=candidate,
            predecessor_event_id=existing.l1_event_id,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update",
        )
        updated = await store.get(entry_id)
    else:
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

    if updated is not None and not projection_changed:
        repaired = await _repair_projection_if_needed(
            entry=updated,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update",
        )
        if repaired:
            updated = await _load_projection_state(store, entry_id)
            if (
                updated.deleted_at is not None
                or updated.delete_requested_at is not None
            ):
                raise await _terminal_source_conflict(
                    projector=projector,
                    entry=updated,
                    predecessor_event_id=updated.l1_event_id,
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
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="entry not found",
        )
    if (
        existing.deleted_at is not None
        or existing.delete_requested_at is not None
    ):
        raise await _terminal_source_conflict(
            projector=projector,
            entry=existing,
            predecessor_event_id=existing.l1_event_id,
        )
    if existing.pending_l1_event_id is not None:
        await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_weather_repair",
        )
        existing = await _load_projection_state(store, entry_id)
        if (
            existing.deleted_at is not None
            or existing.delete_requested_at is not None
        ):
            raise await _terminal_source_conflict(
                projector=projector,
                entry=existing,
                predecessor_event_id=existing.l1_event_id,
            )
    if existing.weather is None:
        repaired = await _repair_projection_if_needed(
            entry=existing,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_weather_clear",
        )
        if repaired:
            existing = await _load_projection_state(store, entry_id)
            if (
                existing.deleted_at is not None
                or existing.delete_requested_at is not None
            ):
                raise await _terminal_source_conflict(
                    projector=projector,
                    entry=existing,
                    predecessor_event_id=existing.l1_event_id,
                )
        return _entry_to_dict(existing)

    candidate = replace(existing, weather=None)
    await _replace_and_project(
        entry=candidate,
        predecessor_event_id=existing.l1_event_id,
        store=store,
        projector=projector,
        memory=memory,
        reason="manual_entry_weather_clear",
    )

    return _entry_to_dict(candidate)


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
