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
from dataclasses import dataclass
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
    CandidateResolution,
    SuggestionCandidate,
    build_suggestion_candidates,
    partition_for_candidates,
)
from magi.system_suggestions.engine import ClassifyFn, run_suggestion_check
from magi.system_suggestions.throttle import SuggestionThrottle

logger = get_logger(__name__)

# A candidates builder returns the installed∪registry union plus whether the
# full catalog was available. Production awaits the registry, so the inner
# callable may return the resolution directly or as a coroutine.
CandidatesResult = Union[CandidateResolution, Awaitable[CandidateResolution]]
CandidatesDep = Callable[[], Callable[[], CandidatesResult]]
# Given the resolved candidate list, return a (plugin_id) -> bool adapter so the
# engine can resolve availability per-candidate (installed vs registry-only).
AvailabilityDep = Callable[[], Callable[[list[SuggestionCandidate]], Callable[[str], bool]]]
IsDismissedDep = Callable[[], Callable[[str], bool]]
# The inner writer accepts (dedupe_key, kind, title=None); title is optional so
# callers may pass two or three args. ``...`` keeps two-arg fakes type-valid.
RecordDismissalDep = Callable[[], Callable[..., None]]
ListDismissalsDep = Callable[[], Callable[[], list["DismissalItem"]]]
ClearDismissalDep = Callable[[], Callable[[str], bool]]
ClassifyDep = Callable[[], ClassifyFn]

# Process-wide throttle: avoids re-running the LLM classifier on every /check.
# State is keyed by session_id; resets on worker restart.
_THROTTLE = SuggestionThrottle(reclassify_after=3)


@dataclass(slots=True)
class _SystemSuggestionsRouteHandlers:
    candidates_dep: CandidatesDep
    availability_dep: AvailabilityDep
    is_dismissed_dep: IsDismissedDep
    record_dismissal_dep: RecordDismissalDep
    list_dismissals_dep: ListDismissalsDep
    clear_dismissal_dep: ClearDismissalDep
    classify_dep: ClassifyDep

    async def check(self, request: CheckRequest) -> CheckResponse:
        candidates = (await self._resolve_candidates()).candidates
        is_available = self.availability_dep()(candidates)
        proposals = await run_suggestion_check(
            recent_text=request.text,
            locale=request.locale,
            session_id=request.session_id,
            candidates=candidates,
            is_available=is_available,
            is_dismissed=self.is_dismissed_dep(),
            classify=self.classify_dep(),
            throttle=_THROTTLE,
        )
        await _try_materialize_suggestion_notifications(
            locale=request.locale,
            proposals=proposals,
        )
        return CheckResponse(suggestions=proposals)

    async def dismiss(self, request: DismissRequest) -> DismissResponse:
        record = self.record_dismissal_dep()
        record(request.dedupe_key, request.kind.value, request.title)
        return DismissResponse(dedupe_key=request.dedupe_key, dismissed=True)

    async def list_dismissals(self) -> ListDismissalsResponse:
        return ListDismissalsResponse(dismissals=self.list_dismissals_dep()())

    async def clear_dismissal(self, dedupe_key: str) -> ClearDismissalResponse:
        cleared = self.clear_dismissal_dep()(dedupe_key)
        return ClearDismissalResponse(dedupe_key=dedupe_key, cleared=cleared)

    async def list_installable(self) -> ListInstallableResponse:
        resolution = await self._resolve_candidates()
        candidates = resolution.candidates
        is_available = self.availability_dep()(candidates)
        return ListInstallableResponse(
            items=[
                _installable_item(candidate)
                for candidate in candidates
                if is_available(candidate.plugin_id)
            ],
            catalog_mode=resolution.catalog_mode,
        )

    async def _resolve_candidates(self) -> CandidateResolution:
        result = self.candidates_dep()()
        return await result if inspect.isawaitable(result) else result


def _installable_item(candidate: SuggestionCandidate) -> InstallableItem:
    return InstallableItem(
        plugin_id=candidate.plugin_id,
        name=candidate.name,
        name_i18n=candidate.name_i18n,
        description=candidate.description,
        description_i18n=candidate.description_i18n,
        icon=candidate.icon,
        category=candidate.descriptor.category,
        installed=candidate.installed,
        rationale={
            "zh": candidate.descriptor.rationale.zh,
            "en": candidate.descriptor.rationale.en,
        },
        setup_time_estimate_seconds=candidate.descriptor.setup_time_estimate_seconds,
        data_locality=candidate.descriptor.data_locality,
        surfaces=candidate.descriptor.surfaces,
    )


async def _try_materialize_suggestion_notifications(
    *,
    locale: str,
    proposals: object,
) -> None:
    try:
        from magi.notifications.service import materialize_suggestion_notifications

        await materialize_suggestion_notifications(
            user_id="default_user",
            locale=locale,
            proposals=proposals,
        )
    except Exception:
        logger.warning("notification materialization failed", exc_info=True)


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
    handlers = _SystemSuggestionsRouteHandlers(
        candidates_dep=candidates_dep,
        availability_dep=availability_dep,
        is_dismissed_dep=is_dismissed_dep,
        record_dismissal_dep=record_dismissal_dep,
        list_dismissals_dep=list_dismissals_dep,
        clear_dismissal_dep=clear_dismissal_dep,
        classify_dep=classify_dep,
    )

    router.post("/system-suggestions/check", response_model=CheckResponse)(handlers.check)
    router.post("/system-suggestions/dismiss", response_model=DismissResponse)(handlers.dismiss)
    router.get("/system-suggestions/dismissals", response_model=ListDismissalsResponse)(
        handlers.list_dismissals
    )
    router.delete(
        "/system-suggestions/dismissals/{dedupe_key}",
        response_model=ClearDismissalResponse,
    )(handlers.clear_dismissal)
    router.get("/system-suggestions/installable", response_model=ListInstallableResponse)(
        handlers.list_installable
    )

    return router


# ---------------------------------------------------------------------------
# Production dependency wiring
# ---------------------------------------------------------------------------


async def _active_sensor_plugin_ids() -> set[str]:
    """Plugin ids whose sensor source is already in use (enabled AND configured).

    Reuses the sensor-source status the frontend reads, so "in use" matches what
    the user sees in Settings. Degrades to an empty set on any error (we'd rather
    occasionally re-suggest an active plugin than crash the suggestion path).
    """
    try:
        from magi.api.routers.sensors import get_sensor_source_status

        status = await get_sensor_source_status()
        sources = (status or {}).get("sources", []) if isinstance(status, dict) else []
        active: set[str] = set()
        for s in sources:
            pid = s.get("plugin_id")
            if not pid or not s.get("enabled"):
                continue
            # "configured": the activation flow's configured_key is truthy in
            # current_settings, OR the source doesn't require activation.
            # get_sensor_source_status exposes `activation_required` = True only
            # when an activation flow exists AND it's not yet enabled+configured.
            # So: in-use == enabled AND not activation_required.
            if not s.get("activation_required", False):
                active.add(str(pid))
        return active
    except Exception as exc:  # noqa: BLE001 - degrade, never crash /check
        logger.warning("system_suggestions active-source lookup failed", error=str(exc))
        return set()


def _default_candidates() -> Callable[[], CandidatesResult]:
    """Return an async builder of the installed∪registry candidate union.

    Installed manifests come from the live plugin manager; registry entries
    (with a ``suggestion_descriptor``) come from the shared registry client's
    async ``fetch_index``. On ANY registry failure we degrade to installed-only
    and log a warning, so the route never fails just because the registry is
    unreachable.

    Plugins whose sensor source is already in use (enabled+configured, per
    :func:`_active_sensor_plugin_ids`) are dropped via
    :func:`partition_for_candidates` so we never suggest connecting/installing a
    data source the user already has on.
    """
    from magi.api.routers.plugins_common import _get_registry_client, _try_plugin_manager

    async def _build() -> CandidateResolution:
        manager = _try_plugin_manager()
        packages = list(manager.list_packages()) if manager else []

        registry_entries: list = []
        catalog_mode = "full"
        try:
            index = await _get_registry_client().fetch_index()
            registry_entries = list(index.plugins)
        except Exception as exc:  # degrade to installed-only
            catalog_mode = "installed_only"
            logger.warning(
                ("registry fetch failed for suggestion candidates; degrading to installed-only"),
                error=str(exc),
            )
            registry_entries = []

        active_plugin_ids = await _active_sensor_plugin_ids()
        installed_manifests, not_installed_registry = partition_for_candidates(
            packages, registry_entries, active_plugin_ids
        )
        return CandidateResolution(
            candidates=build_suggestion_candidates(
                installed_manifests,
                not_installed_registry,
            ),
            catalog_mode=catalog_mode,
        )

    return _build


# Module-scoped lock so we don't double-create the resolver if two requests
# race on first access.
_AVAILABILITY_ADAPTER_LOCK = Lock()


def _default_availability() -> Callable[[list[SuggestionCandidate]], Callable[[str], bool]]:
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
            return resolver.evaluate_descriptor(cand.descriptor, plugin_id=plugin_id).available

        return _is_available

    return _factory


def _default_is_dismissed() -> Callable[[str], bool]:
    """Return ``(dedupe_key) -> bool`` over the live dismissal map."""
    from magi.system_suggestions.dismissals import (
        is_dismissal_active,
        load_dismissals_from_config,
    )

    def _is_dismissed(dedupe_key: str) -> bool:
        records = load_dismissals_from_config()
        rec = records.get(dedupe_key)
        if rec is None:
            return False
        return is_dismissal_active(rec)

    return _is_dismissed


def _default_record_dismissal() -> Callable[[str, str], None]:
    """Return the shared config-backed dismissal writer (GET → mutate → PUT)."""
    from magi.system_suggestions.dismissals import record_dismissal

    return record_dismissal


def _default_list_dismissals():
    from magi.api.routers.system_suggestions_schemas import DismissalItem
    from magi.system_suggestions.dismissals import list_active_dismissals

    def _list():
        return [
            DismissalItem(
                dedupe_key=r.dedupe_key,
                dismissed_at=r.dismissed_at,
                kind=r.kind,
                title=r.title,
            )
            for r in list_active_dismissals()
        ]

    return _list


def _default_clear_dismissal():
    from magi.system_suggestions.dismissals import clear_dismissal

    return clear_dismissal


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
