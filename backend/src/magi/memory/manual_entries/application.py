"""Retry-safe manual-entry application workflows, independent of HTTP."""

from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from magi.memory.application_errors import MemoryApplicationError
from .commands import ManualEntryCreateBody, ManualEntryUpdateBody

import time
from dataclasses import replace
from functools import wraps
from typing import TYPE_CHECKING, Any, Optional
from magi.core.logger import get_logger
from magi.memory.manual_entries import ManualEntry
from magi.memory.manual_entries.l1_projector import ManualEntryProjectionGovernedError
from magi.memory.manual_entries.locks import entry_mutation_lock as _entry_mutation_lock
from magi.memory.manual_entries.workflow import (
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


if TYPE_CHECKING:
    from .store import ManualEntryStore
    from .asset_store import ManualEntryAssetStore
    from .l1_projector import ManualEntryL1Projector
    from .weather_fetcher import WeatherFetcher
    from magi.location.store import LocationSampleStore
    from magi.memory.unified_store import UnifiedMemoryStore


@dataclass(frozen=True, slots=True)
class ManualEntryDependencies:
    store: ManualEntryStore
    assets: ManualEntryAssetStore
    projector: ManualEntryL1Projector | None
    weather: WeatherFetcher | None
    location_samples: LocationSampleStore | None
    memory: UnifiedMemoryStore | None


logger = get_logger(__name__)


def _memory_clear_conflict() -> MemoryApplicationError:
    return MemoryApplicationError(
        reason="conflict",
        detail={
            "code": "memory_clear_in_progress",
            "message": "Memory is being cleared; retry after the clear finishes",
        },
    )


def _guard_manual_entry_write(handler):
    """Reject stale manual-entry writes instead of replaying them after a clear."""

    @wraps(handler)
    async def guarded(*args, **kwargs):
        memory = kwargs["services"].memory
        if memory is None:
            raise MemoryApplicationError(
                reason="unavailable", detail="Memory system not initialized"
            )
        captured_epoch = memory.memory_operation_epoch()
        if memory.memory_clear_in_progress():
            raise _memory_clear_conflict()
        async with memory.memory_operation_guard():
            if (
                memory.memory_clear_in_progress()
                or captured_epoch != memory.memory_operation_epoch()
            ):
                raise _memory_clear_conflict()
            return await handler(*args, **kwargs)

    return guarded


def _entry_to_dict(entry: ManualEntry) -> dict:
    return entry.to_dict()


def _create_response(entry: ManualEntry, *, projection_unconfirmed: bool) -> dict:
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
    if all((asset_store.has_asset(asset_ref) for asset_ref in attachment_refs)):
        return
    raise MemoryApplicationError(
        reason="invalid_request", detail="Attachment reference is invalid or unavailable"
    )


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
            body.body_doc is not None and body.body_doc != existing.body_doc,
            body.clear_body_doc and existing.body_doc is not None,
            body.event_at is not None and float(body.event_at) != float(existing.event_at),
            body.mood is not None and (body.mood or None) != existing.mood,
            body.attachment_refs is not None
            and list(body.attachment_refs) != list(existing.attachments),
            body.location_label is not None
            and (body.location_label or None) != existing.location_label,
        )
    )


def _memory_cleanup_error() -> MemoryApplicationError:
    return MemoryApplicationError(
        reason="unavailable", detail="Memory cleanup did not complete; retry the request"
    )


def _memory_projection_error() -> MemoryApplicationError:
    return MemoryApplicationError(
        reason="unavailable", detail="Memory projection did not complete; retry the request"
    )


def _memory_forgotten_error(
    *, reason: str, source_preserved: bool = False
) -> MemoryApplicationError:
    return MemoryApplicationError(
        reason="conflict",
        detail={
            "code": "manual_entry_memory_forgotten",
            "reason": str(reason or "source_reference"),
            "retry_as_new": not source_preserved,
            "source_preserved": source_preserved,
            "message": "This occurrence is covered by a durable memory-forget rule",
        },
    )


def _deletion_in_progress_error() -> MemoryApplicationError:
    return _memory_forgotten_error(reason="source_reference")


def _workflow_error(exc: ManualEntryWorkflowError) -> MemoryApplicationError:
    if isinstance(exc, ManualEntryGovernanceRejectedError):
        return _memory_forgotten_error(reason=exc.reason, source_preserved=exc.source_preserved)
    if isinstance(exc, ManualEntryCleanupError):
        return _memory_cleanup_error()
    if isinstance(exc, ManualEntryProjectionError):
        return _memory_projection_error()
    if isinstance(exc, ManualEntryDeletionInProgressError):
        return _deletion_in_progress_error()
    if isinstance(exc, ManualEntryNotFoundError):
        return MemoryApplicationError(reason="not_found", detail="entry not found")
    if isinstance(exc, ManualEntryDeleteStartError):
        return MemoryApplicationError(
            reason="unavailable", detail="Manual entry deletion did not start; retry the request"
        )
    if isinstance(exc, ManualEntryDeleteCompletionError):
        return MemoryApplicationError(
            reason="unavailable", detail="Manual entry deletion did not complete; retry the request"
        )
    if isinstance(exc, ManualEntryDeleteConflictError):
        return MemoryApplicationError(
            reason="conflict", detail="entry changed while it was being deleted; retry the request"
        )
    return MemoryApplicationError(
        reason="unavailable", detail="Manual entry operation did not complete; retry the request"
    )


async def _load_projection_state(store, entry_id: str) -> ManualEntry:
    try:
        return await ManualEntryWorkflow(
            store=store, projector=None, memory=None
        ).load_projection_state(entry_id)
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


async def _project_and_link(
    *, entry: ManualEntry, predecessor_event_id: str | None, store, projector, memory
) -> None:
    try:
        await ManualEntryWorkflow(store=store, projector=projector, memory=memory).project_and_link(
            entry=entry, predecessor_event_id=predecessor_event_id
        )
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


async def _replace_and_project(
    *, entry: ManualEntry, predecessor_event_id: str | None, store, projector, memory, reason: str
) -> None:
    try:
        await ManualEntryWorkflow(
            store=store, projector=projector, memory=memory
        ).replace_and_project(entry=entry, predecessor_event_id=predecessor_event_id, reason=reason)
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


async def _repair_projection_if_needed(
    *, entry: ManualEntry, store, projector, memory, reason: str
) -> bool:
    try:
        return await ManualEntryWorkflow(
            store=store, projector=projector, memory=memory
        ).repair_projection_if_needed(entry=entry, reason=reason)
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc


def _create_request_matches(existing: ManualEntry, body: ManualEntryCreateBody) -> bool:
    """Compare only user-controlled create fields for idempotent retries."""
    return bool(
        existing.kind == "quick"
        and existing.body == body.body
        and (existing.body_doc == body.body_doc)
        and (body.event_at is None or float(existing.event_at) == float(body.event_at))
        and (existing.mood == (body.mood or None))
        and (existing.location_label == (body.location_label or None))
        and (existing.location_lat == body.location_lat)
        and (existing.location_lng == body.location_lng)
        and (list(existing.attachments) == list(body.attachment_refs))
    )


def _create_identity_conflict() -> MemoryApplicationError:
    return MemoryApplicationError(
        reason="conflict", detail="entry identity is already used by different content"
    )


async def _terminal_source_conflict(
    *, projector, entry: ManualEntry, predecessor_event_id: str | None = None
) -> MemoryApplicationError:
    """Describe a terminal source identity with its current governance rule."""
    reason = "source_reference"
    if projector is not None:
        try:
            await projector.ensure_projectable(entry, predecessor_event_id=predecessor_event_id)
        except ManualEntryProjectionGovernedError as exc:
            reason = exc.reason
        except Exception:
            pass
    return _memory_forgotten_error(reason=reason)


async def _resolve_weather_coords(*, location_samples, entry) -> Optional[tuple[float, float]]:
    """Return (lat, lng) for the weather lookup, or None if unresolvable.

    Priority:
      1. The entry's own ``location_lat / location_lng`` (frontend may pass
         these if the user picked a place with attached coords).
      2. The most recent location sample at or before ``event_at`` — even
         if the user typed the label by hand, the ambient location is a
         strict-improvement over nothing.
    """
    if entry.location_lat is not None and entry.location_lng is not None:
        return (float(entry.location_lat), float(entry.location_lng))
    if location_samples is None:
        return None
    try:
        sample = await location_samples.latest(before=entry.event_at)
    except Exception:
        return None
    if sample is None or sample.lat is None or sample.lng is None:
        return None
    return (float(sample.lat), float(sample.lng))


async def _attach_weather(*, weather_fetcher, location_samples, store, entry) -> Optional[dict]:
    """Best-effort: fetch weather and persist it onto the entry.

    Returns the weather dict on success (also mutates entry in-place so
    callers can hand it straight to the L1 projector); None on any
    failure path. Never raises — weather is decorative.
    """
    weather = await _fetch_weather(
        weather_fetcher=weather_fetcher, location_samples=location_samples, entry=entry
    )
    if weather is None:
        return None
    try:
        persisted = await store.set_weather(entry.entry_id, weather)
    except Exception:
        try:
            confirmed = await store.get(entry.entry_id)
        except Exception:
            return None
        if confirmed is None or confirmed.deleted_at is not None or confirmed.weather != weather:
            return None
        entry.weather = dict(confirmed.weather)
        return entry.weather
    if not persisted:
        return None
    entry.weather = weather
    return weather


async def _fetch_weather(*, weather_fetcher, location_samples, entry) -> Optional[dict]:
    """Resolve weather without mutating the source row."""
    if weather_fetcher is None:
        return None
    coords = await _resolve_weather_coords(location_samples=location_samples, entry=entry)
    if coords is None:
        return None
    lat, lng = coords
    try:
        weather = await weather_fetcher.fetch(lat=lat, lng=lng, event_at=entry.event_at)
    except Exception:
        return None
    return weather or None


def _apply_entry_update(existing: ManualEntry, body: ManualEntryUpdateBody) -> ManualEntry:
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


@_guard_manual_entry_write
async def create_manual_entry(
    body: ManualEntryCreateBody, *, services: ManualEntryDependencies
) -> dict:
    """Create a new entry and project it to L1.

    ``event_at`` defaults to ``time.time()`` when null — covers the
    common "writing about now" case without forcing the client to send
    a timestamp it just got from ``Date.now()``.
    """
    store, asset_store, projector, weather_fetcher, location_samples, memory = (
        services.store,
        services.assets,
        services.projector,
        services.weather,
        services.location_samples,
        services.memory,
    )
    if not body.body.strip() and (not body.attachment_refs):
        raise MemoryApplicationError(
            reason="invalid_request", detail="entry must have body text or at least one attachment"
        )
    _validate_attachment_refs(asset_store, body.attachment_refs)
    async with _entry_mutation_lock(body.entry_id):
        try:
            existing = await store.get(body.entry_id)
        except Exception as exc:
            raise MemoryApplicationError(
                reason="unavailable",
                detail="Manual entry storage did not complete; retry the request",
            ) from exc
        if existing is not None:
            if existing.deleted_at is not None or existing.delete_requested_at is not None:
                raise await _terminal_source_conflict(projector=projector, entry=existing)
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
                    await projector.ensure_projectable(entry, predecessor_event_id=None)
                except ManualEntryProjectionGovernedError as exc:
                    raise _memory_forgotten_error(reason=exc.reason) from exc
                except Exception as exc:
                    raise _memory_projection_error() from exc
        try:
            if existing is None:
                await store.create(entry)
        except Exception as exc:
            try:
                persisted = await store.get(entry.entry_id)
            except Exception as read_exc:
                raise MemoryApplicationError(
                    reason="unavailable",
                    detail="Manual entry storage did not complete; retry the request",
                ) from read_exc
            if persisted is None:
                raise MemoryApplicationError(
                    reason="unavailable",
                    detail="Manual entry storage did not complete; retry the request",
                ) from exc
            if persisted.deleted_at is not None or persisted.delete_requested_at is not None:
                raise await _terminal_source_conflict(projector=projector, entry=persisted) from exc
            if not _create_request_matches(persisted, body):
                raise _create_identity_conflict() from exc
            entry = persisted
        if (
            entry.l1_event_id is None
            and entry.pending_l1_event_id is None
            and (entry.weather is None)
        ):
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
        except MemoryApplicationError as exc:
            if exc.reason != "unavailable":
                raise
            projection_unconfirmed = True
            logger.warning(
                "Manual-entry projection deferred after source save",
                entry_id=entry.entry_id,
                error=exc.detail,
            )
        try:
            persisted = await _load_projection_state(store, entry.entry_id)
        except MemoryApplicationError:
            if not projection_unconfirmed:
                raise
        else:
            if persisted.deleted_at is not None or persisted.delete_requested_at is not None:
                raise await _terminal_source_conflict(projector=projector, entry=persisted)
            entry = persisted
    return _create_response(entry, projection_unconfirmed=projection_unconfirmed)


async def list_manual_entries(
    time_start: float,
    time_end: float,
    limit: int = 500,
    *,
    services: ManualEntryDependencies,
) -> dict:
    store, _, _, _, _, _ = (
        services.store,
        services.assets,
        services.projector,
        services.weather,
        services.location_samples,
        services.memory,
    )
    entries = await store.list_window(
        time_start=time_start, time_end=time_end, include_deleted=False, limit=limit
    )
    return {"items": [_entry_to_dict(e) for e in entries]}


async def get_manual_entry(entry_id: str, *, services: ManualEntryDependencies) -> dict:
    """Read the current authored entry for an explicit editor reload."""
    store, *_ = (
        services.store,
        services.assets,
        services.projector,
        services.weather,
        services.location_samples,
        services.memory,
    )
    entry = await store.get(entry_id)
    if entry is None or entry.deleted_at is not None or entry.delete_requested_at is not None:
        raise MemoryApplicationError(reason="not_found", detail="Entry not found")
    if entry.pending_l1_event_id is not None:
        raise MemoryApplicationError(
            reason="unavailable", detail="Entry update is still being reconciled"
        )
    return _entry_to_dict(entry)


@_guard_manual_entry_write
async def update_manual_entry(
    entry_id: str, body: ManualEntryUpdateBody, *, services: ManualEntryDependencies
) -> dict:
    async with _entry_mutation_lock(entry_id):
        return await _update_manual_entry_locked(entry_id, body, services=services)


async def _update_manual_entry_locked(
    entry_id: str, body: ManualEntryUpdateBody, *, services: ManualEntryDependencies
) -> dict:
    store, asset_store, projector, weather_fetcher, location_samples, memory = (
        services.store,
        services.assets,
        services.projector,
        services.weather,
        services.location_samples,
        services.memory,
    )
    existing = await store.get(entry_id)
    if existing is None:
        raise MemoryApplicationError(reason="not_found", detail="entry not found")
    if existing.deleted_at is not None or existing.delete_requested_at is not None:
        raise await _terminal_source_conflict(
            projector=projector, entry=existing, predecessor_event_id=existing.l1_event_id
        )
    if not body.expected_revision:
        raise MemoryApplicationError(
            reason="precondition_required", detail="Manual entry revision is required"
        )
    if body.expected_revision != existing.revision and _has_entry_changes(existing, body):
        raise MemoryApplicationError(
            reason="conflict",
            detail={
                "code": "manual_entry_conflict",
                "message": "Entry changed; reload before saving",
            },
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
        if existing.deleted_at is not None or existing.delete_requested_at is not None:
            raise await _terminal_source_conflict(
                projector=projector, entry=existing, predecessor_event_id=existing.l1_event_id
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
            if existing.deleted_at is not None or existing.delete_requested_at is not None:
                raise await _terminal_source_conflict(
                    projector=projector, entry=existing, predecessor_event_id=existing.l1_event_id
                )
        return _entry_to_dict(existing)
    final_body = body.body if body.body is not None else existing.body
    final_attachments = (
        list(body.attachment_refs)
        if body.attachment_refs is not None
        else list(existing.attachments)
    )
    if not final_body.strip() and (not final_attachments):
        raise MemoryApplicationError(
            reason="invalid_request", detail="entry must have body text or at least one attachment"
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
            weather_fetcher=weather_fetcher, location_samples=location_samples, entry=candidate
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
            raise MemoryApplicationError(
                reason="conflict",
                detail="entry changed while it was being updated; retry the request",
            )
        updated = await store.get(entry_id)
    if updated is not None and (not projection_changed):
        repaired = await _repair_projection_if_needed(
            entry=updated,
            store=store,
            projector=projector,
            memory=memory,
            reason="manual_entry_update",
        )
        if repaired:
            updated = await _load_projection_state(store, entry_id)
            if updated.deleted_at is not None or updated.delete_requested_at is not None:
                raise await _terminal_source_conflict(
                    projector=projector, entry=updated, predecessor_event_id=updated.l1_event_id
                )
    return _entry_to_dict(updated or existing)


@_guard_manual_entry_write
async def clear_manual_entry_weather(entry_id: str, *, services: ManualEntryDependencies) -> dict:
    """Drop the auto-resolved weather snapshot.

    Reached via the ✕ button on the chip in the QuickEntrySheet. We
    don't allow setting weather from the client — only clearing —
    because user-supplied weather isn't meaningfully better than no
    chip, and accepting writes would invite garbage data.

    Re-projects to L1 so downstream consumers see the absence too.
    """
    async with _entry_mutation_lock(entry_id):
        return await _clear_manual_entry_weather_locked(entry_id, services=services)


async def _clear_manual_entry_weather_locked(
    entry_id: str, *, services: ManualEntryDependencies
) -> dict:
    store, _, projector, _, _, memory = (
        services.store,
        services.assets,
        services.projector,
        services.weather,
        services.location_samples,
        services.memory,
    )
    existing = await store.get(entry_id)
    if existing is None:
        raise MemoryApplicationError(reason="not_found", detail="entry not found")
    if existing.deleted_at is not None or existing.delete_requested_at is not None:
        raise await _terminal_source_conflict(
            projector=projector, entry=existing, predecessor_event_id=existing.l1_event_id
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
        if existing.deleted_at is not None or existing.delete_requested_at is not None:
            raise await _terminal_source_conflict(
                projector=projector, entry=existing, predecessor_event_id=existing.l1_event_id
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
            if existing.deleted_at is not None or existing.delete_requested_at is not None:
                raise await _terminal_source_conflict(
                    projector=projector, entry=existing, predecessor_event_id=existing.l1_event_id
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


@_guard_manual_entry_write
async def delete_manual_entry(entry_id: str, *, services: ManualEntryDependencies) -> dict:
    async with _entry_mutation_lock(entry_id):
        return await _delete_manual_entry_locked(entry_id, services=services)


async def _delete_manual_entry_locked(entry_id: str, *, services: ManualEntryDependencies) -> dict:
    store, _, projector, _, _, memory = (
        services.store,
        services.assets,
        services.projector,
        services.weather,
        services.location_samples,
        services.memory,
    )
    try:
        result = await ManualEntryWorkflow(
            store=store, projector=projector, memory=memory
        ).delete_entry(entry_id)
    except ManualEntryWorkflowError as exc:
        raise _workflow_error(exc) from exc
    if result.already_deleted:
        return {"ok": True, "already_deleted": True}
    return {"ok": True}


@_guard_manual_entry_write
async def upload_manual_entry_asset(
    upload_image: Callable[[], Awaitable[dict]], *, services: ManualEntryDependencies
) -> dict:
    """Keep asset writes inside the same clear barrier as entry writes."""
    return await upload_image()
