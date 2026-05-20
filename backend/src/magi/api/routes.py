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
        "/embeddings/status": {"GET"},
        "/embeddings/rebuild": {"POST"},
        "/embeddings/rebuild/{job_id}": {"GET"},
        "/embeddings/rebuild/{job_id}/cancel": {"POST"},
        "/search": {"POST"},
        "/procedures": {"GET"},
        "/tom/{entity_id}": {"GET"},
        "/portrait": {"GET"},
        "/portrait/self": {"GET"},
        "/stories": {"GET"},
        "/stories/{summary_id}/review": {"PATCH"},
        "/manual-entries": {"GET", "POST"},
        "/manual-entries/{entry_id}": {"PATCH", "DELETE"},
        "/manual-entries/assets": {"POST"},
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
        "/session/{session_id}/detach-run": {"POST"},
        "/session/{session_id}/message/{message_id}": {"DELETE"},
        "/session/{session_id}/message/{message_id}/label": {"POST"},
        "/sessions": {"GET"},
    },
    "config": {
        "/": {"GET", "PUT"},
        "/template": {"GET"},
        "/test": {"POST"},
        "/embedding-preflight": {"POST"},
        "/channels/telegram/test": {"POST"},
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
    "hooks": {
        "/api/hooks": {"GET"},
        "/api/hooks/": {"GET"},
    },
    "timeline": {
        "/viewport": {"GET"},
        "/context/{anchor_id}": {"GET"},
        "/standout": {"GET"},
        "/mood-calendar": {"GET"},
        "/asset/{asset_ref}": {"GET"},
    },
    "sensors": {
        "/status": {"GET"},
        "/today-summary": {"GET"},
        "/{source_name}/sync": {"POST"},
        "/{source_name}/flush-state": {"POST"},
        "/{source_name}/authorize": {"POST"},
    },
    "plugins": {
        "": {"GET"},
        "/rescan": {"POST"},
        "/registry": {"GET"},
        "/updates": {"GET"},
        "/{plugin_id}/update": {"POST"},
        "/{plugin_id}/update/jobs": {"POST"},
        "/install/upload": {"POST"},
        "/install/upload/jobs": {"POST"},
        "/install/registry": {"POST"},
        "/install/registry/jobs": {"POST"},
        "/install/jobs/{job_id}": {"GET"},
        "/{plugin_id}": {"DELETE"},
        "/{plugin_id}/enable": {"POST"},
        "/{plugin_id}/disable": {"POST"},
        "/{plugin_id}/reload": {"POST"},
        "/{plugin_id}/settings": {"GET", "PUT"},
        "/{plugin_id}/settings/resources/{resource_name}": {"GET"},
        "/{plugin_id}/settings/actions/{action_id}/start": {"POST"},
        "/{plugin_id}/settings/actions/{action_id}/sessions/{session_id}/poll": {"POST"},
        "/{plugin_id}/settings/actions/{action_id}/sessions/{session_id}/cancel": {"POST"},
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
        "/greeting": {"GET"},
        "/generate": {"POST"},
        "/generation-jobs": {"POST"},
        "/generation-jobs/{job_id}": {"GET"},
        "/bootstrap/init": {"POST"},
        "/journal/reflect": {"POST"},
    },
    "personality_presets": {
        "/": {"GET"},
        "/avatar/upload": {"POST"},
        "/{preset_id}": {"GET"},
    },
    "personas": {
        "/": {"GET", "POST"},
        "/active": {"GET", "PUT"},
        "/seed-previews": {"GET"},
        "/seed": {"POST"},
        "/{persona_id}": {"GET", "PUT", "DELETE"},
    },
    "background_tasks": {
        "": {"GET"},
        "/{task_id}": {"GET"},
        "/{task_id}/cancel": {"POST"},
        "/{task_id}/retry": {"POST"},
        "/{task_id}/dismiss": {"POST"},
    },
    "schedules": {
        "": {"GET", "POST"},
        "/activity": {"GET"},
        "/activity/{activity_id}/cancel": {"POST"},
        "/{schedule_id}": {"DELETE", "GET", "PATCH"},
        "/{schedule_id}/run": {"POST"},
    },
    "control": {
        "/settings": {"GET", "PUT"},
        "/sessions/{session_id}/settings": {"GET", "PUT"},
        "/rules": {"GET", "DELETE"},
        "/rules/{rule_id}": {"DELETE"},
        "/permission/{request_id}/respond": {"POST"},
        "/ask/{request_id}/respond": {"POST"},
        "/sessions/{session_id}/plan": {"GET"},
        "/sessions/{session_id}/todos": {"GET"},
        "/sessions/{session_id}/permissions": {"GET"},
        "/sessions/{session_id}/ask": {"GET"},
    },
    "mcp": {
        "/servers": {"GET", "POST"},
        "/servers/{server_id}": {"PATCH", "DELETE"},
        "/servers/{server_id}/start": {"POST"},
        "/servers/{server_id}/stop": {"POST"},
        "/servers/{server_id}/logs": {"GET"},
        "/resources": {"GET"},
        "/resources/read": {"POST"},
    },
    "commands": {
        "/": {"GET"},
        "/run": {"POST"},
        "/skills": {"GET"},
        "/expand-skill": {"POST"},
        "/run-skill-as-background": {"POST"},
    },
    "code_agent": {
        "/probe": {"GET"},
        "/rescan": {"POST"},
        "/settings": {"GET", "PATCH"},
        "/settings/reset": {"POST"},
        "/delegations/{session_id}/{delegation_id}": {"GET"},
        "/delegations/{session_id}/{delegation_id}/cancel": {"POST"},
        "/delegations/{session_id}/{delegation_id}/apply": {"POST"},
        "/delegations/{session_id}/{delegation_id}/discard": {"POST"},
    },
    "profile": {
        "/me": {"GET", "PATCH"},
        "/me/refresh": {"POST"},
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
        user_messages_router,
        config_router,
        llm_router,
        personality_config_router,
        personality_presets_router,
        personas_router,
        skills_router,
        hooks_router,
        sensors_router,
        timeline_router,
        plugins_router,
        local_embedding_router,
        local_reranker_router,
        background_tasks_router,
        schedules_router,
        control_router,
        mcp_router,
        commands_router,
        code_agent_router,
        profile_router,
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
        _build_public_router(personas_router, _PUBLIC_ROUTE_METHODS["personas"]),
        prefix="/api/personas",
        tags=["Personas"],
    )
    app.include_router(
        _build_public_router(skills_router, _PUBLIC_ROUTE_METHODS["skills"]),
        tags=["Skills"],
    )
    app.include_router(
        _build_public_router(hooks_router, _PUBLIC_ROUTE_METHODS["hooks"]),
        tags=["Hooks"],
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
        _build_public_router(local_embedding_router, _PUBLIC_ROUTE_METHODS["local_embedding"]),
        prefix="/api/local-embedding",
        tags=["Local Embedding"],
    )
    app.include_router(
        _build_public_router(local_reranker_router, _PUBLIC_ROUTE_METHODS["local_reranker"]),
        prefix="/api/local-reranker",
        tags=["Local Reranker"],
    )
    app.include_router(
        _build_public_router(background_tasks_router, _PUBLIC_ROUTE_METHODS["background_tasks"]),
        prefix="/api/background-tasks",
        tags=["Background Tasks"],
    )
    app.include_router(
        _build_public_router(schedules_router, _PUBLIC_ROUTE_METHODS["schedules"]),
        prefix="/api/schedules",
        tags=["Schedules"],
    )
    app.include_router(
        _build_public_router(control_router, _PUBLIC_ROUTE_METHODS["control"]),
        prefix="/api/control",
        tags=["Control"],
    )
    app.include_router(
        _build_public_router(mcp_router, _PUBLIC_ROUTE_METHODS["mcp"]),
        prefix="/api/mcp",
        tags=["MCP"],
    )
    app.include_router(
        _build_public_router(commands_router, _PUBLIC_ROUTE_METHODS["commands"]),
        prefix="/api/commands",
        tags=["Commands"],
    )
    app.include_router(
        _build_public_router(code_agent_router, _PUBLIC_ROUTE_METHODS["code_agent"]),
        prefix="/api/code_agent",
        tags=["CodeAgent"],
    )
    app.include_router(
        _build_public_router(profile_router, _PUBLIC_ROUTE_METHODS["profile"]),
        prefix="/api/profile",
        tags=["Profile"],
    )
