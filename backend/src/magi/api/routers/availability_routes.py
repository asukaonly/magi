"""HTTP API for the availability subsystem.

Two endpoints:
- GET  /availability               — query availability of plugins
- POST /availability/refresh       — invalidate cache for a set (or all)
"""

from __future__ import annotations

from datetime import timedelta
from threading import Lock
from typing import Callable

from fastapi import APIRouter, Body, Query

from magi.api.routers.availability_schemas import (
    AvailabilityEntry,
    AvailabilityListResponse,
    AvailabilityRefreshResponse,
)
from magi.availability import AvailabilityResolver

from .plugins_common import _try_plugin_manager

ResolverDep = Callable[[], AvailabilityResolver]
PluginIdsDep = Callable[[], list[str]]


# Module-scoped lazily-initialized resolver. Mirrors the shared plugin API
# helpers that keep one process-local client/cache per router process.
_resolver: AvailabilityResolver | None = None
_resolver_lock = Lock()


def _default_manifest_provider(plugin_id: str):
    manager = _try_plugin_manager()
    if manager is None:
        return None
    pkg = manager.get_package(plugin_id)
    return pkg.manifest if pkg else None


def _default_all_plugin_ids() -> list[str]:
    manager = _try_plugin_manager()
    if manager is None:
        return []
    return [pkg.manifest.plugin_id for pkg in manager.list_packages()]


def _get_or_create_resolver() -> AvailabilityResolver:
    global _resolver
    with _resolver_lock:
        if _resolver is None:
            _resolver = AvailabilityResolver(
                manifest_provider=_default_manifest_provider,
                ttl=timedelta(minutes=5),
            )
        return _resolver


def create_availability_router(
    resolver_dep: ResolverDep,
    all_plugin_ids_dep: PluginIdsDep,
) -> APIRouter:
    """Construct the router given dependency callables.

    Router declares full sub-paths (``/availability``, ``/availability/refresh``).
    Mount with ``prefix='/api'`` in production (see
    :func:`magi.api.routes.register_api_routes`), or with no prefix in tests
    that hit ``/availability`` directly.

        app.include_router(
            create_availability_router(
                lambda: app.state.availability_resolver,
                lambda: [p.manifest.plugin_id for p in plugin_manager.list_packages()],
            ),
            prefix="/api",
        )
    """
    router = APIRouter()

    @router.get("/availability", response_model=AvailabilityListResponse)
    async def list_availability(
        plugin_ids: str | None = Query(
            default=None,
            description=(
                "Comma-separated list of plugin IDs. If omitted, all known "
                "plugins are returned."
            ),
        ),
    ) -> AvailabilityListResponse:
        resolver = resolver_dep()
        ids: list[str]
        if plugin_ids is None:
            ids = all_plugin_ids_dep()
        else:
            ids = [s.strip() for s in plugin_ids.split(",") if s.strip()]

        entries: list[AvailabilityEntry] = []
        for plugin_id in ids:
            result = resolver.is_available(plugin_id)
            entries.append(
                AvailabilityEntry(
                    plugin_id=result.plugin_id,
                    available=result.available,
                    reason=result.reason,
                    detail=result.detail,
                    checked_at=result.checked_at,
                )
            )
        return AvailabilityListResponse(entries=entries)

    @router.post("/availability/refresh", response_model=AvailabilityRefreshResponse)
    async def refresh_availability(
        body: dict = Body(default_factory=dict),
    ) -> AvailabilityRefreshResponse:
        resolver = resolver_dep()
        ids = body.get("plugin_ids") if isinstance(body, dict) else None
        if not ids:
            resolver.invalidate()
            return AvailabilityRefreshResponse(invalidated_plugin_ids=[])
        for pid in ids:
            resolver.invalidate(pid)
        return AvailabilityRefreshResponse(invalidated_plugin_ids=list(ids))

    return router


def build_default_availability_router() -> APIRouter:
    """Construct an availability router wired to the live plugin manager.

    Used by :func:`magi.api.routes.register_api_routes` so the production
    app exposes the endpoints. Tests construct their own router via
    :func:`create_availability_router` for isolation.
    """
    return create_availability_router(
        resolver_dep=_get_or_create_resolver,
        all_plugin_ids_dep=_default_all_plugin_ids,
    )


# Module-level router used by the public route filter in
# :mod:`magi.api.routes`. Constructed at import time so that
# ``_PUBLIC_ROUTE_METHODS`` can match its registered paths.
availability_router: APIRouter = build_default_availability_router()


__all__ = [
    "availability_router",
    "build_default_availability_router",
    "create_availability_router",
]
