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
        "/clear": {"DELETE"},
        "/eval/replay": {"POST"},
        "/eval/query": {"POST"},
        "/eval/finalize-replay": {"POST"},
        "/background/pending": {"GET"},
        "/identity/links": {"GET"},
        "/l2/statistics": {"GET"},
        "/l2/relations": {"GET"},
        "/l2/assertions": {"GET"},
        "/l2/entities": {"GET"},
        "/l2/mentions": {"GET"},
        "/l2/snapshots": {"GET"},
        "/l2/conflict-rules": {"GET"},
        "/l2/conflict-rules/{predicate}": {"PUT"},
        "/l2/microbatch-flush": {"POST"},
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
        "/session/{session_id}/attachments": {"POST"},
        "/session/{session_id}/attachments/{attachment_id}/content": {"GET"},
        "/session/{session_id}/workspace": {"PATCH"},
        "/session/{session_id}/cancel-run": {"POST"},
        "/session/{session_id}/message/{message_id}": {"DELETE"},
        "/session/{session_id}/message/{message_id}/label": {"POST"},
        "/sessions": {"GET"},
    },
    "config": {
        "/": {"GET", "PUT"},
        "/template": {"GET"},
        "/test": {"POST"},
        "/onboarding-template": {"GET"},
        "/onboarding-complete": {"POST"},
    },
    "llm": {
        "/providers/catalog": {"GET", "POST"},
        "/providers/custom-template": {"GET"},
        "/providers/discover-models": {"POST"},
        "/providers/test": {"POST"},
    },
    "skills": {
        "/api/skills/": {"GET"},
    },
    "timeline": {
        "/viewport": {"GET"},
        "/context/{anchor_id}": {"GET"},
    },
    "sensors": {
        "/status": {"GET"},
        "/{source_name}/sync": {"POST"},
        "/{source_name}/flush-state": {"POST"},
        "/{source_name}/authorize": {"POST"},
    },
    "plugins": {
        "": {"GET"},
        "/rescan": {"POST"},
        "/{plugin_id}/enable": {"POST"},
        "/{plugin_id}/disable": {"POST"},
        "/{plugin_id}/reload": {"POST"},
        "/{plugin_id}/settings": {"GET", "PUT"},
        "/{plugin_id}/settings/resources/{resource_name}": {"GET"},
    },
    "local_embedding": {
        "/models": {"GET"},
        "/models/{model_id}/download": {"POST"},
        "/models/{model_id}/status": {"GET"},
        "/models/{model_id}": {"DELETE"},
        "/discovered": {"GET"},
    },
    "local_reranker": {
        "/models": {"GET"},
        "/models/{model_id}/download": {"POST"},
        "/models/{model_id}/status": {"GET"},
        "/models/{model_id}": {"DELETE"},
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
    "schedules": {
        "/": {"GET", "POST"},
        "/executions/recent": {"GET"},
        "/{schedule_id}": {"GET", "PATCH", "DELETE"},
        "/{schedule_id}/trigger": {"POST"},
        "/{schedule_id}/executions": {"GET"},
    },
    "tasks": {
        "/": {"GET", "POST"},
        "/{task_id}": {"GET", "PATCH", "DELETE"},
        "/orchestration/{orchestration_id}": {"GET"},
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
        llm_router,
        personality_config_router,
        personality_presets_router,
        skills_router,
        sensors_router,
        timeline_router,
        plugins_router,
        schedules_router,
        tasks_router,
        local_embedding_router,
        local_reranker_router,
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
        _build_public_router(llm_router, _PUBLIC_ROUTE_METHODS["llm"]),
        prefix="/api/llm",
        tags=["LLM"],
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
        _build_public_router(sensors_router, _PUBLIC_ROUTE_METHODS["sensors"]),
        prefix="/api/sensors",
        tags=["Sensors"],
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
    app.include_router(
        _build_public_router(schedules_router, _PUBLIC_ROUTE_METHODS["schedules"]),
        prefix="/api/schedules",
        tags=["Schedules"],
    )
    app.include_router(
        _build_public_router(tasks_router, _PUBLIC_ROUTE_METHODS["tasks"]),
        prefix="/api/tasks",
        tags=["Tasks"],
    )
    app.include_router(
        _build_public_router(local_embedding_router, _PUBLIC_ROUTE_METHODS["local_embedding"]),
        prefix="/api/local-embedding",
        tags=["Local Embedding"],
    )
    app.include_router(
        _build_public_router(local_reranker_router, _PUBLIC_ROUTE_METHODS["local_reranker"]),
        prefix="/api/local-reranker",
        tags=["Local Reranker"],
    )
