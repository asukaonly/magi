"""API route registration for external services."""

from __future__ import annotations

from collections.abc import Mapping, Set

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute


_PUBLIC_ROUTE_METHODS: dict[str, dict[str, set[str]]] = {
    "tools": {
        "/config": {"GET"},
        "/{tool_name}/config": {"GET", "PUT"},
    },
    "memory": {
        "/l0/sessions": {"GET"},
        "/l0/workbench/{session_id}": {"GET"},
        "/l1/events": {"GET"},
        "/l2/statistics": {"GET"},
        "/l2/relations": {"GET"},
        "/l2/assertions": {"GET"},
        "/l2/entities": {"GET"},
        "/l2/mentions": {"GET"},
        "/l2/snapshots": {"GET"},
        "/l2/conflict-rules": {"GET"},
        "/l2/conflict-rules/{predicate}": {"PUT"},
        "/l3/summaries": {"GET"},
        "/statistics": {"GET"},
        "/search": {"POST"},
        "/procedures": {"GET"},
        "/tom/{entity_id}": {"GET"},
    },
    "metrics": {
        "/llm/usage/summary": {"GET"},
        "/llm/usage/timeseries": {"GET"},
        "/runtime/overview": {"GET"},
    },
    "messages": {
        "/send": {"POST"},
        "/history": {"GET"},
        "/trace": {"GET"},
        "/history/clear": {"POST"},
        "/session/new": {"POST"},
        "/session/{session_id}": {"PATCH", "DELETE"},
        "/sessions": {"GET"},
    },
    "config": {
        "/": {"GET", "PUT"},
        "/template": {"GET"},
        "/test": {"POST"},
        "/llm-providers": {"GET"},
        "/llm/providers/discover-models": {"POST"},
        "/llm/providers/test": {"POST"},
        "/onboarding-template": {"GET"},
        "/onboarding-complete": {"POST"},
    },
    "skills": {
        "/api/skills/": {"GET"},
    },
    "timeline": {
        "/items": {"GET"},
        "/events/{event_id}": {"GET"},
        "/manual": {"POST"},
        "/sources/status": {"GET"},
        "/sources/{source_name}/sync": {"POST"},
        "/events/{event_id}/reanalyze": {"POST"},
    },
    "plugins": {
        "": {"GET"},
        "/rescan": {"POST"},
        "/{plugin_id}/enable": {"POST"},
        "/{plugin_id}/disable": {"POST"},
        "/{plugin_id}/reload": {"POST"},
        "/{plugin_id}/settings": {"GET", "PUT"},
    },
    "personality_config": {
        "/": {"GET"},
        "/current": {"GET", "PUT"},
        "/greeting": {"GET"},
        "/generate": {"POST"},
        "/compare/{from_name}/{to_name}": {"GET"},
        "/new": {"PUT"},
        "/{name}": {"GET", "PUT", "DELETE"},
    },
    "personality_presets": {
        "/": {"GET"},
        "/avatar/upload": {"POST"},
        "/{preset_id}": {"GET"},
    },
}


def _build_public_router(source_router: APIRouter, allowed_routes: Mapping[str, Set[str]]) -> APIRouter:
    """Create a filtered router that only exposes approved product endpoints."""
    public_routes = []
    for route in source_router.routes:
        if not isinstance(route, APIRoute):
            continue
        allowed_methods = allowed_routes.get(route.path)
        if not allowed_methods:
            continue
        route_methods = {method for method in (route.methods or set()) if method not in {"HEAD", "OPTIONS"}}
        if route_methods & set(allowed_methods):
            public_routes.append(route)
    return APIRouter(routes=public_routes)


def register_api_routes(app: FastAPI) -> None:
    """Register all product-facing API routes."""
    from .routers import (
        tools_router,
        memory_router,
        metrics_router,
        user_messages_router,
        config_router,
        personality_config_router,
        personality_presets_router,
        skills_router,
        timeline_router,
        plugins_router,
    )

    app.include_router(
        _build_public_router(tools_router, _PUBLIC_ROUTE_METHODS["tools"]),
        prefix="/api/tools",
        tags=["Tools"],
    )
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
        prefix="/api/memory",
        tags=["Memory"],
    )
    app.include_router(
        _build_public_router(metrics_router, _PUBLIC_ROUTE_METHODS["metrics"]),
        prefix="/api/metrics",
        tags=["Metrics"],
    )
    app.include_router(
        _build_public_router(user_messages_router, _PUBLIC_ROUTE_METHODS["messages"]),
        prefix="/api/messages",
        tags=["Messages"],
    )
    app.include_router(
        _build_public_router(config_router, _PUBLIC_ROUTE_METHODS["config"]),
        prefix="/api/config",
        tags=["Config"],
    )
    app.include_router(
        _build_public_router(personality_config_router, _PUBLIC_ROUTE_METHODS["personality_config"]),
        prefix="/api/personality",
        tags=["Personality Config"],
    )
    app.include_router(
        _build_public_router(personality_presets_router, _PUBLIC_ROUTE_METHODS["personality_presets"]),
        prefix="/api/personalities",
        tags=["Personality Presets"],
    )
    app.include_router(
        _build_public_router(skills_router, _PUBLIC_ROUTE_METHODS["skills"]),
        tags=["Skills"],
    )
    app.include_router(
        _build_public_router(timeline_router, _PUBLIC_ROUTE_METHODS["timeline"]),
        prefix="/api/timeline",
        tags=["Timeline"],
    )
    app.include_router(
        _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]),
        prefix="/api/plugins",
        tags=["Plugins"],
    )
