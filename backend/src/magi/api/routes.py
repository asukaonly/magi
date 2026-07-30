"""API route registration for external services."""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Any

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
        "/l1/events/{event_id}": {"DELETE"},
        "/clear": {"DELETE"},
        "/eval/replay": {"POST"},
        "/eval/query": {"POST"},
        "/eval/judge-answer": {"POST"},
        "/eval/finalize-replay": {"POST"},
        "/background/pending": {"GET"},
        "/identity/links": {"GET"},
        "/l2/statistics": {"GET"},
        "/l2/relations": {"GET"},
        "/l2/assertions": {"GET"},
        "/l2/assertions/{assertion_id}/feedback": {"PATCH"},
        "/l2/corrections": {"GET", "POST"},
        "/l2/corrections/{correction_id}/revert": {"POST"},
        "/l2/context-options": {"GET"},
        "/l2/entities": {"GET"},
        "/l2/mentions": {"GET"},
        "/l2/snapshots": {"GET"},
        "/l2/conflict-rules": {"GET"},
        "/l2/conflict-rules/{predicate}": {"PUT"},
        "/l2/microbatch-flush": {"POST"},
        "/l2/episodes": {"GET"},
        "/l2/episodes/{episode_id}": {"GET", "PATCH"},
        "/l2/episodes/{episode_id}/event-candidates": {"GET"},
        "/l2/episodes/{episode_id}/events": {"POST", "DELETE"},
        "/l2/episodes/{episode_id}/regenerate": {"POST"},
        "/l2/episodes/{episode_id}/merge-candidates": {"GET"},
        "/l2/episodes/{episode_id}/merge": {"POST"},
        "/l2/episodes/{episode_id}/split-preview": {"POST"},
        "/l2/episodes/{episode_id}/split": {"POST"},
        "/l2/episodes/reconsolidate": {"POST"},
        "/l2/experience-seeds": {"GET", "POST"},
        "/l2/experience-seeds/{seed_id}/promote": {"POST"},
        "/l2/experience-seeds/{seed_id}/reject": {"POST"},
        "/l2/experience-drafts/organize": {"POST"},
        "/l2/experience-drafts": {"GET"},
        "/l2/experience-drafts/{draft_id}": {"GET", "PATCH"},
        "/l2/experience-drafts/{draft_id}/cover": {"POST"},
        "/l2/experience-drafts/{draft_id}/create": {"POST"},
        "/l2/experiences": {"GET"},
        "/l2/experiences/{experience_id}": {"GET", "PATCH"},
        "/l2/experiences/{experience_id}/cover": {"POST"},
        "/l2/experiences/{experience_id}/hide": {"POST"},
        "/l2/experiences/{experience_id}/regenerate": {"POST"},
        "/forget/entity": {"POST"},
        "/forget/time-range": {"POST"},
        "/forget/episode": {"POST"},
        "/l3/summaries": {"GET"},
        "/dashboard": {"GET"},
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
        "/stories/{summary_id}/evidence": {"GET"},
        "/manual-entries": {"GET", "POST"},
        "/manual-entries/{entry_id}": {"PATCH", "DELETE"},
        "/manual-entries/{entry_id}/weather": {"DELETE"},
        "/manual-entries/assets": {"POST"},
        "/history-imports/markdown/preview": {"POST"},
        "/history-imports": {"GET"},
        "/history-imports/{job_id}": {"GET", "DELETE"},
        "/history-imports/{job_id}/selection": {"PATCH"},
        "/history-imports/{job_id}/confirm": {"POST"},
        "/history-imports/{job_id}/resume": {"POST"},
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
        "/preferences/language": {"PUT"},
        "/test": {"POST"},
        "/embedding-preflight": {"POST"},
        "/channels/telegram/test": {"POST"},
        "/onboarding-status": {"GET"},
        "/onboarding-template": {"GET"},
        "/onboarding-draft": {"PUT"},
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
        # The route is declared with `:path` so the asset_ref can contain
        # both ":" and "/" (e.g. ``manual-entry-asset://<sha>.jpg``,
        # ``photo-library://...``). The gateway's allowlist matches
        # FastAPI's `route.path` string verbatim, so the converter
        # suffix has to be included here too — otherwise the route
        # silently doesn't get mounted on the public router.
        "/asset/{asset_ref:path}": {"GET"},
        "/cover": {"POST"},
    },
    "sensors": {
        "/status": {"GET"},
        "/today-summary": {"GET"},
        "/{source_name}/memory-readiness": {"GET"},
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
        "/install/upload/inspect": {"POST"},
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
        "/adjust": {"POST"},
        "/generate": {"POST"},
        "/generation-intents/resolve": {"POST"},
        "/generation-intents/verify": {"POST"},
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
    "availability": {
        "/availability": {"GET"},
        "/availability/refresh": {"POST"},
    },
    "chat_preview": {
        "/chat/preview": {"POST"},
    },
    "system_suggestions": {
        "/system-suggestions/check": {"POST"},
        "/system-suggestions/dismiss": {"POST"},
        "/system-suggestions/dismissals": {"GET"},
        "/system-suggestions/dismissals/{dedupe_key}": {"DELETE"},
        "/system-suggestions/installable": {"GET"},
    },
    "notifications": {
        "/notifications": {"GET"},
        "/notifications/mark-read": {"POST"},
        "/notifications/dismiss-all": {"POST"},
        "/notifications/{notification_id}/dismiss": {"POST"},
        "/notifications/{notification_id}/action": {"POST"},
        "/notifications/{notification_id}/resolve-conflict": {"POST"},
    },
    "channels_bindings": {
        "/bindings": {"GET"},
        "/bindings/{channel_type}/{external_user_id}/auto-approve": {"PUT"},
    },
}


def _iter_api_routes(router: APIRouter):
    """Yield leaf APIRoutes, descending into included sub-routers.

    fastapi <0.137 flattens ``include_router`` routes into ``router.routes`` as
    plain ``APIRoute`` objects. fastapi >=0.137 instead appends one
    ``_IncludedRouter`` wrapper per ``include_router`` call (no ``.path``),
    exposing the child via ``original_router``. Recurse through both shapes so
    route discovery is fastapi-version-agnostic. (magi's public sub-routers carry
    no prefixes, so leaf ``route.path`` already matches the allowlist keys.)
    """
    for route in getattr(router, "routes", ()):  # default () guards non-router nodes
        if isinstance(route, APIRoute):
            yield route
            continue
        nested = getattr(route, "original_router", None)
        if nested is None and hasattr(route, "routes"):
            nested = route
        if nested is not None and nested is not router:
            yield from _iter_api_routes(nested)


@dataclass(frozen=True)
class _RouterRegistrationSpec:
    router_attr: str
    allowlist_key: str
    prefix: str
    tag: str


_ROUTER_REGISTRATION_SPECS: tuple[_RouterRegistrationSpec, ...] = (
    _RouterRegistrationSpec("tools_router", "tools", "/api/tools", "Tools"),
    _RouterRegistrationSpec("memory_router", "memory", "/api/memory", "Memory"),
    _RouterRegistrationSpec("user_messages_router", "messages", "/api/messages", "Messages"),
    _RouterRegistrationSpec("config_router", "config", "/api/config", "Config"),
    _RouterRegistrationSpec("llm_router", "llm", "/api/llm", "LLM"),
    _RouterRegistrationSpec(
        "personality_config_router",
        "personality_config",
        "/api/personality",
        "Personality Config",
    ),
    _RouterRegistrationSpec(
        "personality_presets_router",
        "personality_presets",
        "/api/personalities",
        "Personality Presets",
    ),
    _RouterRegistrationSpec("personas_router", "personas", "/api/personas", "Personas"),
    _RouterRegistrationSpec("skills_router", "skills", "", "Skills"),
    _RouterRegistrationSpec("hooks_router", "hooks", "", "Hooks"),
    _RouterRegistrationSpec("sensors_router", "sensors", "/api/sensors", "Sensors"),
    _RouterRegistrationSpec("timeline_router", "timeline", "/api/timeline", "Timeline"),
    _RouterRegistrationSpec("plugins_router", "plugins", "/api/plugins", "Plugins"),
    _RouterRegistrationSpec(
        "local_embedding_router",
        "local_embedding",
        "/api/local-embedding",
        "Local Embedding",
    ),
    _RouterRegistrationSpec(
        "local_reranker_router",
        "local_reranker",
        "/api/local-reranker",
        "Local Reranker",
    ),
    _RouterRegistrationSpec(
        "background_tasks_router",
        "background_tasks",
        "/api/background-tasks",
        "Background Tasks",
    ),
    _RouterRegistrationSpec("schedules_router", "schedules", "/api/schedules", "Schedules"),
    _RouterRegistrationSpec("control_router", "control", "/api/control", "Control"),
    _RouterRegistrationSpec("mcp_router", "mcp", "/api/mcp", "MCP"),
    _RouterRegistrationSpec("commands_router", "commands", "/api/commands", "Commands"),
    _RouterRegistrationSpec("code_agent_router", "code_agent", "/api/code_agent", "CodeAgent"),
    _RouterRegistrationSpec("profile_router", "profile", "/api/profile", "Profile"),
    _RouterRegistrationSpec("availability_router", "availability", "/api", "Availability"),
    _RouterRegistrationSpec("chat_preview_router", "chat_preview", "/api", "Chat Preview"),
    _RouterRegistrationSpec(
        "system_suggestions_router",
        "system_suggestions",
        "/api",
        "System Suggestions",
    ),
    _RouterRegistrationSpec("notifications_router", "notifications", "/api", "Notifications"),
    _RouterRegistrationSpec(
        "channels_bindings_router",
        "channels_bindings",
        "/api/channels",
        "Channels",
    ),
)


def _build_public_router(
    source_router: APIRouter, allowed_routes: Mapping[str, Set[str]]
) -> APIRouter:
    """Create a filtered router that only exposes approved product endpoints."""
    public_routes = []
    for route in _iter_api_routes(source_router):
        allowed_methods = allowed_routes.get(route.path)
        if not allowed_methods:
            continue
        route_methods = {
            method for method in (route.methods or set()) if method not in {"HEAD", "OPTIONS"}
        }
        if route_methods & set(allowed_methods):
            public_routes.append(route)
    return APIRouter(routes=public_routes)


def register_api_routes(app: FastAPI) -> None:
    """Register all product-facing API routes."""
    router_module = _public_router_module()
    for registration in _ROUTER_REGISTRATION_SPECS:
        _include_public_router(app, registration, router_module)


def _include_public_router(
    app: FastAPI,
    registration: _RouterRegistrationSpec,
    router_module: Any,
) -> None:
    source_router = getattr(router_module, registration.router_attr)
    app.include_router(
        _build_public_router(
            source_router,
            _PUBLIC_ROUTE_METHODS[registration.allowlist_key],
        ),
        prefix=registration.prefix,
        tags=[registration.tag],
    )


def _public_router_module() -> Any:
    from . import routers

    return routers
