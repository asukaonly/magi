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

- ``candidates_dep`` builds the UNION of installed plugin manifests
  (``installed=True``) and registry-discovered entries that are not installed
  (``installed=False``) into :class:`SuggestionCandidate` objects. Installed
  manifests come from the live plugin manager via
  :func:`magi.api.routers.plugins_common._try_plugin_manager`; registry entries
  come from the shared :class:`PluginRegistryClient` (its async ``fetch_index``
  is awaited). On ANY registry failure the builder degrades to installed-only
  (registry = ``[]``) and logs a warning. The inner callable may be sync (tests)
  or async (production); the ``/check`` handler awaits it if it is a coroutine.
- ``availability_dep`` is a factory that, given the candidate list, returns a
  ``(plugin_id) -> bool`` adapter. Production closes over Plan 1's resolver
  singleton (via ``_get_or_create_resolver``) and resolves availability
  per-candidate: installed candidates go through ``resolver.is_available`` while
  not-installed candidates go through ``resolver.evaluate_descriptor`` so the
  registry descriptor is probed directly without a local manifest.
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

import inspect
from threading import Lock
from typing import Awaitable, Callable, Union

from fastapi import APIRouter

from magi.api.routers.system_suggestions_schemas import (
    CheckRequest,
    CheckResponse,
    ClearDismissalResponse,
    DismissalItem,
    DismissRequest,
    DismissResponse,
    InstallableItem,
    ListDismissalsResponse,
    ListInstallableResponse,
)
from magi.core.logger import get_logger
from magi.system_suggestions.candidates import (
    SuggestionCandidate,
    build_suggestion_candidates,
)
from magi.system_suggestions.engine import ClassifyFn, run_suggestion_check
from magi.system_suggestions.throttle import SuggestionThrottle

logger = get_logger(__name__)

# A candidates builder returns the installed∪registry union; production awaits
# the registry, so the inner callable may return a list directly OR a coroutine.
CandidatesResult = Union[
    list[SuggestionCandidate], Awaitable[list[SuggestionCandidate]]
]
CandidatesDep = Callable[[], Callable[[], CandidatesResult]]
# Given the resolved candidate list, return a (plugin_id) -> bool adapter so the
# engine can resolve availability per-candidate (installed vs registry-only).
AvailabilityDep = Callable[
    [], Callable[[list[SuggestionCandidate]], Callable[[str], bool]]
]
IsDismissedDep = Callable[[], Callable[[str], bool]]
RecordDismissalDep = Callable[[], Callable[[str, str], None]]
ListDismissalsDep = Callable[[], Callable[[], list["DismissalItem"]]]
ClearDismissalDep = Callable[[], Callable[[str], bool]]
ClassifyDep = Callable[[], ClassifyFn]

# Process-wide throttle: avoids re-running the LLM classifier on every /check.
# State is keyed by session_id; resets on worker restart.
_THROTTLE = SuggestionThrottle(reclassify_after=3)


def build_default_system_suggestions_router(
    *,
    candidates_dep: CandidatesDep,
    availability_dep: AvailabilityDep,
    is_dismissed_dep: IsDismissedDep,
    record_dismissal_dep: RecordDismissalDep,
    list_dismissals_dep: ListDismissalsDep,
    clear_dismissal_dep: ClearDismissalDep,
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
        # Resolve the installed∪registry candidate union. The builder may be
        # async (production awaits the registry) or sync (tests/degrade path).
        result = candidates_dep()()
        candidates = await result if inspect.isawaitable(result) else result
        # Per-candidate availability: installed vs registry-only resolve through
        # different resolver entry points (see ``_default_availability``).
        is_available = availability_dep()(candidates)
        proposals = await run_suggestion_check(
            recent_text=request.text,
            locale=request.locale,
            session_id=request.session_id,
            candidates=candidates,
            is_available=is_available,
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

    @router.get(
        "/system-suggestions/dismissals", response_model=ListDismissalsResponse
    )
    async def list_dismissals() -> ListDismissalsResponse:
        return ListDismissalsResponse(dismissals=list_dismissals_dep()())

    @router.delete(
        "/system-suggestions/dismissals/{dedupe_key}",
        response_model=ClearDismissalResponse,
    )
    async def clear_dismissal(dedupe_key: str) -> ClearDismissalResponse:
        cleared = clear_dismissal_dep()(dedupe_key)
        return ClearDismissalResponse(dedupe_key=dedupe_key, cleared=cleared)

    @router.get(
        "/system-suggestions/installable",
        response_model=ListInstallableResponse,
    )
    async def list_installable() -> ListInstallableResponse:
        # Resolve the installed∪registry candidate union (same shape as
        # ``/check``: the builder may be async in production, sync in tests).
        result = candidates_dep()()
        candidates = await result if inspect.isawaitable(result) else result
        is_available = availability_dep()(candidates)
        items = [
            InstallableItem(
                plugin_id=c.plugin_id,
                category=c.descriptor.category,
                installed=c.installed,
                rationale={
                    "zh": c.descriptor.rationale.zh,
                    "en": c.descriptor.rationale.en,
                },
            )
            for c in candidates
            if is_available(c.plugin_id)
        ]
        return ListInstallableResponse(items=items)

    return router


# ---------------------------------------------------------------------------
# Production dependency wiring
# ---------------------------------------------------------------------------


def _default_candidates() -> Callable[[], CandidatesResult]:
    """Return an async builder of the installed∪registry candidate union.

    Installed manifests come from the live plugin manager; registry entries
    (with a ``suggestion_descriptor``) come from the shared registry client's
    async ``fetch_index``. On ANY registry failure we degrade to installed-only
    and log a warning, so the route never fails just because the registry is
    unreachable.
    """
    from magi.api.routers.plugins_common import _get_registry_client, _try_plugin_manager

    async def _build() -> list[SuggestionCandidate]:
        manager = _try_plugin_manager()
        installed = (
            [pkg.manifest for pkg in manager.list_packages()] if manager else []
        )

        registry_entries: list = []
        try:
            index = await _get_registry_client().fetch_index()
            registry_entries = list(index.plugins)
        except Exception as exc:  # degrade to installed-only
            logger.warning(
                "registry fetch failed for suggestion candidates; "
                "degrading to installed-only",
                error=str(exc),
            )
            registry_entries = []

        return build_suggestion_candidates(installed, registry_entries)

    return _build


# Module-scoped lock so we don't double-create the resolver if two requests
# race on first access.
_AVAILABILITY_ADAPTER_LOCK = Lock()


def _default_availability() -> Callable[
    [list[SuggestionCandidate]], Callable[[str], bool]
]:
    """Return a factory that builds a per-candidate availability adapter.

    Given the resolved candidate list, returns a ``(plugin_id) -> bool`` that
    resolves availability per-candidate against Plan 1's resolver singleton:

    * installed candidates -> ``resolver.is_available(plugin_id)`` (manifest
      lookup + TTL cache).
    * not-installed (registry-only) candidates ->
      ``resolver.evaluate_descriptor(descriptor)`` so the registry descriptor's
      platform + local requirements are probed directly without a local
      manifest.
    """
    from magi.api.routers.availability_routes import _get_or_create_resolver

    with _AVAILABILITY_ADAPTER_LOCK:
        resolver = _get_or_create_resolver()

    def _factory(
        candidates: list[SuggestionCandidate],
    ) -> Callable[[str], bool]:
        by_id = {c.plugin_id: c for c in candidates}

        def _is_available(plugin_id: str) -> bool:
            cand = by_id.get(plugin_id)
            if cand is None:
                # Unknown to the candidate set: fall back to the installed path.
                return resolver.is_available(plugin_id).available
            if cand.installed:
                return resolver.is_available(plugin_id).available
            return resolver.evaluate_descriptor(
                cand.descriptor, plugin_id=plugin_id
            ).available

        return _is_available

    return _factory


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


def _default_list_dismissals():
    from magi.api.routers.system_suggestions_schemas import DismissalItem
    from magi.system_suggestions.dismissals import is_dismissal_active

    def _list():
        records = _load_dismissals_from_config()
        return [
            DismissalItem(dedupe_key=k, dismissed_at=r.dismissed_at, kind=r.kind)
            for k, r in records.items()
            if is_dismissal_active(r)
        ]

    return _list


def _default_clear_dismissal():
    from magi.config import get_loader, save_config

    def _clear(dedupe_key: str) -> bool:
        loader = get_loader()
        if loader is not None:
            loader.load()
        prefs = (loader.get_raw_value("preferences", default={}) if loader else {}) or {}
        if not isinstance(prefs, dict):
            prefs = {}
        dismissals = prefs.get("suggestion_dismissals")
        if not isinstance(dismissals, dict) or dedupe_key not in dismissals:
            return False
        del dismissals[dedupe_key]
        prefs["suggestion_dismissals"] = dismissals
        save_config({"preferences": prefs})
        return True

    return _clear


def _default_classify() -> ClassifyFn:
    """Return the production async classifier (core-model batch classify)."""
    from magi.system_suggestions.llm_classifier import classify_with_core_model

    return classify_with_core_model


def _build_production_system_suggestions_router() -> APIRouter:
    """Construct the router wired to live plugin manager + config + resolver."""
    return build_default_system_suggestions_router(
        candidates_dep=_default_candidates,
        availability_dep=_default_availability,
        is_dismissed_dep=_default_is_dismissed,
        record_dismissal_dep=_default_record_dismissal,
        list_dismissals_dep=_default_list_dismissals,
        clear_dismissal_dep=_default_clear_dismissal,
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
