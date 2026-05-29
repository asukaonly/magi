"""HTTP API for /system-suggestions — check + dismiss.

Two endpoints:

- POST /system-suggestions/check — run the matcher against ``text`` and return
  ranked :class:`SuggestionProposal` records. The matcher consumes the live
  plugin manifests + Plan 1's :class:`AvailabilityResolver` + the user's
  current dismissal map.
- POST /system-suggestions/dismiss — record a dismissal in
  ``UserPreferencesModel.suggestion_dismissals`` (TTL applied per
  :class:`DismissalKind`).

Production wiring (see :func:`_build_production_system_suggestions_router`):

- ``list_manifests_dep`` reads from the live plugin manager via
  :func:`magi.api.routers.plugins_common._try_plugin_manager`. Mirrors
  ``_default_all_plugin_ids`` in :mod:`availability_routes`.
- ``is_available_dep`` wraps Plan 1's resolver singleton via
  ``_get_or_create_resolver`` (re-exported from :mod:`availability_routes`)
  and returns a ``(plugin_id) -> bool`` adapter.
- ``is_dismissed_dep`` reads ``preferences.suggestion_dismissals`` from the
  live config and applies :func:`is_dismissal_active`.
- ``record_dismissal_dep`` follows the safe GET → mutate → PUT pattern:
  load the full preferences dict, set ``suggestion_dismissals[dedupe_key]``,
  write the merged preferences back via :func:`magi.config.save_config` with
  the top-level ``preferences`` path. This mirrors how the frontend safely
  mutates preferences via the full-config endpoint and avoids overwriting
  any unrelated fields.

Tests inject their own callables for isolation.
"""

from __future__ import annotations

from threading import Lock
from typing import Callable

from fastapi import APIRouter

from magi.api.routers.system_suggestions_schemas import (
    CheckRequest,
    CheckResponse,
    DismissRequest,
    DismissResponse,
)
from magi.system_suggestions.engine import ClassifyFn, run_suggestion_check
from magi.system_suggestions.throttle import SuggestionThrottle
from magi_plugin_sdk.contracts import PluginManifest

ListManifestsDep = Callable[[], Callable[[], list[PluginManifest]]]
IsAvailableDep = Callable[[], Callable[[str], bool]]
IsDismissedDep = Callable[[], Callable[[str], bool]]
RecordDismissalDep = Callable[[], Callable[[str, str], None]]
ClassifyDep = Callable[[], ClassifyFn]

# Process-wide throttle: avoids re-running the LLM classifier on every /check.
# State is keyed by session_id; resets on worker restart.
_THROTTLE = SuggestionThrottle(reclassify_after=3)


def build_default_system_suggestions_router(
    *,
    list_manifests_dep: ListManifestsDep,
    is_available_dep: IsAvailableDep,
    is_dismissed_dep: IsDismissedDep,
    record_dismissal_dep: RecordDismissalDep,
    classify_dep: ClassifyDep,
) -> APIRouter:
    """Construct the router given dependency callables.

    Mount with ``prefix='/api'`` in production (final paths:
    ``/api/system-suggestions/check``, ``/api/system-suggestions/dismiss``) or
    without prefix in tests that POST to ``/system-suggestions/*`` directly.
    """
    router = APIRouter()

    @router.post("/system-suggestions/check", response_model=CheckResponse)
    async def check(request: CheckRequest) -> CheckResponse:
        proposals = await run_suggestion_check(
            recent_text=request.text,
            locale=request.locale,
            session_id=request.session_id,
            plugin_manifests=list_manifests_dep()(),
            is_available=is_available_dep(),
            is_dismissed=is_dismissed_dep(),
            classify=classify_dep(),
            throttle=_THROTTLE,
        )
        return CheckResponse(suggestions=proposals)

    @router.post("/system-suggestions/dismiss", response_model=DismissResponse)
    async def dismiss(request: DismissRequest) -> DismissResponse:
        record = record_dismissal_dep()
        record(request.dedupe_key, request.kind.value)
        return DismissResponse(dedupe_key=request.dedupe_key, dismissed=True)

    return router


# ---------------------------------------------------------------------------
# Production dependency wiring
# ---------------------------------------------------------------------------


def _default_list_manifests() -> Callable[[], list[PluginManifest]]:
    """Return a callable that reads all installed plugin manifests."""
    from magi.api.routers.plugins_common import _try_plugin_manager

    def _list() -> list[PluginManifest]:
        manager = _try_plugin_manager()
        if manager is None:
            return []
        return [pkg.manifest for pkg in manager.list_packages()]

    return _list


# Module-scoped lock so we don't double-create the resolver if two requests
# race on first access.
_AVAILABILITY_ADAPTER_LOCK = Lock()


def _default_is_available() -> Callable[[str], bool]:
    """Return a ``(plugin_id) -> bool`` adapter over Plan 1's resolver."""
    from magi.api.routers.availability_routes import _get_or_create_resolver

    with _AVAILABILITY_ADAPTER_LOCK:
        resolver = _get_or_create_resolver()

    def _is_available(plugin_id: str) -> bool:
        return resolver.is_available(plugin_id).available

    return _is_available


def _load_dismissals_from_config() -> dict[str, "DismissalRecord"]:
    """Load the current dismissal map from the live config.

    Reads ``preferences.suggestion_dismissals`` from the running
    :class:`AppConfig`. Returns an empty dict if the config or section is
    missing. Records are coerced into :class:`DismissalRecord` so callers can
    apply TTL logic uniformly.
    """
    from magi.config import get_loader
    from magi.system_suggestions.contracts import DismissalRecord

    loader = get_loader()
    if loader is None:
        return {}
    raw = loader.get_raw_value("preferences", "suggestion_dismissals", default={})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, DismissalRecord] = {}
    for key, value in raw.items():
        if isinstance(value, DismissalRecord):
            out[key] = value
            continue
        if isinstance(value, dict):
            try:
                out[key] = DismissalRecord.model_validate(value)
            except Exception:
                continue
    return out


def _default_is_dismissed() -> Callable[[str], bool]:
    """Return ``(dedupe_key) -> bool`` over the live dismissal map."""
    from magi.system_suggestions.dismissals import is_dismissal_active

    def _is_dismissed(dedupe_key: str) -> bool:
        records = _load_dismissals_from_config()
        rec = records.get(dedupe_key)
        if rec is None:
            return False
        return is_dismissal_active(rec)

    return _is_dismissed


def _default_record_dismissal() -> Callable[[str, str], None]:
    """Return a writer that persists a dismissal via GET → mutate → PUT.

    Loads the current ``preferences`` block from the live config, sets
    ``suggestion_dismissals[dedupe_key]`` to a fresh
    :class:`DismissalRecord`, then writes the entire merged ``preferences``
    block back via :func:`save_config`. This mirrors the safe full-config
    pattern the frontend uses for ``first_conversation_completed`` and avoids
    clobbering unrelated preference fields.
    """
    from datetime import datetime, timezone

    from magi.config import get_loader, save_config
    from magi.system_suggestions.contracts import DismissalKind, DismissalRecord

    def _record(dedupe_key: str, kind: str) -> None:
        loader = get_loader()
        # If the loader hasn't been initialized yet (e.g. during very early
        # boot), prime it via save_config's internal lazy init.
        if loader is not None:
            loader.load()
        preferences_raw = (
            loader.get_raw_value("preferences", default={}) if loader else {}
        )
        if not isinstance(preferences_raw, dict):
            preferences_raw = {}
        # Mutate in-place: the dismissals map lives under preferences.
        dismissals = preferences_raw.get("suggestion_dismissals")
        if not isinstance(dismissals, dict):
            dismissals = {}
        record = DismissalRecord(
            dedupe_key=dedupe_key,
            dismissed_at=datetime.now(timezone.utc),
            kind=DismissalKind(kind),
        )
        dismissals[dedupe_key] = record.model_dump(mode="json")
        preferences_raw["suggestion_dismissals"] = dismissals
        save_config({"preferences": preferences_raw})

    return _record


def _default_classify() -> ClassifyFn:
    """Return the production async classifier (core-model batch classify)."""
    from magi.system_suggestions.llm_classifier import classify_with_core_model

    return classify_with_core_model


def _build_production_system_suggestions_router() -> APIRouter:
    """Construct the router wired to live plugin manager + config + resolver."""
    return build_default_system_suggestions_router(
        list_manifests_dep=_default_list_manifests,
        is_available_dep=_default_is_available,
        is_dismissed_dep=_default_is_dismissed,
        record_dismissal_dep=_default_record_dismissal,
        classify_dep=_default_classify,
    )


# Module-level router used by the public route filter in
# :mod:`magi.api.routes`. Constructed at import time so that
# ``_PUBLIC_ROUTE_METHODS`` can match its registered paths.
system_suggestions_router: APIRouter = _build_production_system_suggestions_router()


__all__ = [
    "build_default_system_suggestions_router",
    "system_suggestions_router",
]
