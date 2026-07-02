"""FastAPI HTTP application assembly for the transport layer."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from ..api.avatar_paths import builtin_avatar_dir, user_avatar_dir
from ..api.services import get_runtime_system_status
from ..api.routes import register_api_routes
from ..core.logger import configure_logging, get_logger
from ..utils.runtime import get_runtime_paths
from .http_middleware import (
    ErrorHandler,
    LanguageContextMiddleware,
    RequestLoggingMiddleware,
)

logger = get_logger(__name__, category="API")


def _schedule_process_shutdown(*, delay_seconds: float = 0.1) -> None:
    """Schedule a graceful process shutdown after the current response is sent."""

    async def _shutdown_later() -> None:
        await asyncio.sleep(delay_seconds)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(_shutdown_later())


def _build_custom_openapi(app: FastAPI):
    """Build app-scoped OpenAPI generator."""

    def custom_openapi():
        if not app.openapi_schema:
            openapi_schema = get_openapi(
                title="Magi AI Agent Framework API",
                version="1.0.0",
                description="""
                ## Magi AI Agent Framework API

                RESTful API for the agent system: agent lifecycle, task management, tools, and more.

                ### Features
                - Agent management (create, query, start, stop)
                - Task management (create, query, retry)
                - Tool management (list, details, test)
                - Memory management (search, details, delete)
                - Metrics (performance, state)

                ### Authentication
                Production requires JWT token authentication (disabled in development).
                """,
                routes=app.routes,
            )
            openapi_schema["info"]["x-logo"] = {
                "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png",
            }
            app.openapi_schema = openapi_schema
        return app.openapi_schema

    return custom_openapi


def create_transport_app(*, lifespan: Any = None) -> FastAPI:
    """Create the FastAPI transport app."""
    _configure_transport_logging()
    app = _new_transport_app(lifespan=lifespan)
    app.openapi = _build_custom_openapi(app)

    _add_transport_middleware(app)
    register_api_routes(app)
    _register_health_routes(app)
    _register_docs_routes(app)
    _mount_avatar_static(app)
    return app


def _configure_transport_logging() -> None:
    runtime_paths = get_runtime_paths()
    log_file = runtime_paths.logs_dir / "magi.log"
    configure_logging(
        level="INFO",
        log_file=str(log_file),
        json_logs=False,
    )


def _new_transport_app(*, lifespan: Any = None) -> FastAPI:
    return FastAPI(
        title="Magi AI Agent Framework API",
        description="AI Agent Framework RESTful API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )


def _add_transport_middleware(app: FastAPI) -> None:
    app.add_middleware(ErrorHandler)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(LanguageContextMiddleware)


def _register_health_routes(app: FastAPI) -> None:
    @app.get("/api/health", tags=["Health"])
    async def health_check():
        runtime_status = await get_runtime_system_status(app)
        return {
            "success": True,
            "message": "System health status",
            "data": {
                "status": runtime_status["status"],
                "version": "1.0.0",
                "api_ready": runtime_status["api_ready"],
                "runtime_ready": runtime_status["runtime_ready"],
                "worker_ready": runtime_status["worker_ready"],
                "infrastructure_ready": runtime_status["infrastructure_ready"],
                "llm_ready": runtime_status["llm_ready"],
                "agent_runtime_ready": runtime_status["agent_runtime_ready"],
                "runtime_status": runtime_status["runtime_status"],
                "startup_state": runtime_status["startup_state"],
                "deferred_reason": runtime_status["deferred_reason"],
                "startup_detail": runtime_status["startup_detail"],
                "queue_backlog_healthy": runtime_status["queue_backlog_healthy"],
                "pending_commands": runtime_status["pending_commands"],
            },
        }

    @app.get("/api/ready", tags=["Health"])
    async def ready_check():
        runtime_status = await get_runtime_system_status(app)
        return {
            "success": True,
            "message": "Backend startup state",
            "data": {
                "ready": runtime_status["runtime_ready"]
                and runtime_status["queue_backlog_healthy"],
                "status": runtime_status["status"],
                "runtime_ready": runtime_status["runtime_ready"],
                "worker_ready": runtime_status["worker_ready"],
                "llm_ready": runtime_status["llm_ready"],
                "agent_runtime_ready": runtime_status["agent_runtime_ready"],
                "runtime_status": runtime_status["runtime_status"],
                "startup_state": runtime_status["startup_state"],
                "deferred_reason": runtime_status["deferred_reason"],
            },
        }

    @app.post("/api/runtime/shutdown", tags=["Health"])
    async def runtime_shutdown():
        _schedule_process_shutdown()
        return {
            "success": True,
            "message": "Runtime shutdown scheduled",
            "data": {"scheduled": True},
        }


def _register_docs_routes(app: FastAPI) -> None:
    @app.get("/api/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title="Magi API Docs",
        )

    @app.get("/api/openapi.json", include_in_schema=False)
    async def get_openapi_endpoint():
        return app.openapi()


def _mount_avatar_static(app: FastAPI) -> None:
    avatar_dir = builtin_avatar_dir()
    if avatar_dir.exists():
        app.mount("/static/avatars", StaticFiles(directory=str(avatar_dir)), name="avatars")
        logger.info(f"Avatar static files mounted: {avatar_dir}")

    custom_avatar_dir = user_avatar_dir()
    custom_avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/user-avatars", StaticFiles(directory=str(custom_avatar_dir)), name="user-avatars"
    )
    logger.info(f"User avatar static files mounted: {custom_avatar_dir}")
