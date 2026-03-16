"""API route registration for external services."""

from __future__ import annotations

from fastapi import FastAPI


def register_api_routes(app: FastAPI) -> None:
    """Register all product-facing API routes."""
    from .routers import (
        agents_router,
        tasks_router,
        tools_router,
        memory_router,
        metrics_router,
        user_messages_router,
        config_router,
        personality_config_router,
        personality_presets_router,
        others_router,
        skills_router,
        timeline_router,
        plugins_router,
    )

    app.include_router(agents_router, prefix="/api/agents", tags=["Agents"])
    app.include_router(tasks_router, prefix="/api/tasks", tags=["Tasks"])
    app.include_router(tools_router, prefix="/api/tools", tags=["Tools"])
    app.include_router(memory_router, prefix="/api/memory", tags=["Memory"])
    app.include_router(metrics_router, prefix="/api/metrics", tags=["Metrics"])
    app.include_router(user_messages_router, prefix="/api/messages", tags=["Messages"])
    app.include_router(config_router, prefix="/api/config", tags=["Config"])
    app.include_router(personality_config_router, prefix="/api/personality", tags=["Personality Config"])
    app.include_router(personality_presets_router, prefix="/api/personalities", tags=["Personality Presets"])
    app.include_router(others_router, prefix="/api/others", tags=["Others"])
    app.include_router(skills_router, tags=["Skills"])
    app.include_router(timeline_router, prefix="/api/timeline", tags=["Timeline"])
    app.include_router(plugins_router, prefix="/api/plugins", tags=["Plugins"])
