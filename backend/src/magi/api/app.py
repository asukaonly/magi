"""
FastAPI应用主file

createandConfigurationFastAPI应用Instance
"""
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Any

from .avatar_paths import builtin_avatar_dir, user_avatar_dir
from .middleware import errorHandler, AuthMiddleware, RequestLoggingMiddleware, LanguageContextMiddleware, add_cors_middleware
from .websocket import register_websocket
from ..core.logger import configure_logging, get_logger

logger = get_logger(__name__, category="API")


def _build_custom_openapi(app: FastAPI):
    """Build app-scoped OpenAPI generator."""

    def custom_openapi():
        if not app.openapi_schema:
            openapi_schema = get_openapi(
                title="Magi AI Agent Framework API",
                version="1.0.0",
                description="""
                ## Magi AI Agent Framework API

                Agent系统的RESTful API，提供Agent管理、任务管理、tool管理等function。

                ### functionfeature
                - Agent管理（create、query、启动、stop）
                - 任务管理（create、query、重试）
                - tool管理（list、详情、Test）
                - memory管理（search、详情、delete）
                - metricmonitor（performance、State）

                ### authentication
                生产环境需要JWT tokenauthentication（开发环境已Disable）
                """,
                routes=app.routes,
            )
            openapi_schema["info"]["x-logo"] = {
                "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"
            }
            app.openapi_schema = openapi_schema
        return app.openapi_schema

    return custom_openapi


def create_app(*, lifespan: Any = None) -> FastAPI:
    """
    createFastAPI应用Instance

    Returns:
        FastAPI应用Instance
    """
    # ConfigurationLog（Output到run时directoryand终端）
    from ..utils.runtime import get_runtime_paths
    runtime_paths = get_runtime_paths()
    log_file = runtime_paths.logs_dir / "magi.log"

    configure_logging(
        level="INFO",
        log_file=str(log_file),
        json_logs=False,
    )

    app = FastAPI(
        title="Magi AI Agent Framework API",
        description="AI Agent Framework RESTful API",
        version="1.0.0",
        docs_url=None,  # Disabledefaultdocument，使用customroute
        redoc_url=None,
        lifespan=lifespan,
    )

    # SettingcustomOpenAPI
    app.openapi = _build_custom_openapi(app)

    # addmiddle件
    add_cors_middleware(app)
    app.add_middleware(errorHandler)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(LanguageContextMiddleware)

    # registerroute
    _register_routes(app)

    # add健康check端点
    @app.get("/api/health", tags=["Health"])
    async def health_check():
        """健康check"""
        return {
            "success": True,
            "message": "System is healthy",
            "data": {
                "status": "healthy",
                "version": "1.0.0",
            },
        }

    # adddocument端点
    @app.get("/api/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        """customSwagger UI"""
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title="Magi API Docs",
        )

    @app.get("/api/openapi.json", include_in_schema=False)
    async def get_openapi_endpoint():
        """getOpenAPI schema"""
        return app.openapi()

    # Register WebSocket endpoint
    register_websocket(app)

    # 挂载静态头像目录
    avatar_dir = builtin_avatar_dir()
    if avatar_dir.exists():
        app.mount("/static/avatars", StaticFiles(directory=str(avatar_dir)), name="avatars")
        logger.info(f"Avatar static files mounted: {avatar_dir}")

    custom_avatar_dir = user_avatar_dir()
    custom_avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/user-avatars", StaticFiles(directory=str(custom_avatar_dir)), name="user-avatars")
    logger.info(f"User avatar static files mounted: {custom_avatar_dir}")

    return app


def _register_routes(app: FastAPI):
    """
    registerallroute

    Args:
        app: FastAPI应用Instance
    """
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

    # registerAgent管理route
    app.include_router(
        agents_router,
        prefix="/api/agents",
        tags=["Agents"],
    )

    # register任务管理route
    app.include_router(
        tasks_router,
        prefix="/api/tasks",
        tags=["Tasks"],
    )

    # registertool管理route
    app.include_router(
        tools_router,
        prefix="/api/tools",
        tags=["Tools"],
    )

    # registermemory管理route
    app.include_router(
        memory_router,
        prefix="/api/memory",
        tags=["Memory"],
    )

    # registermetricmonitorroute
    app.include_router(
        metrics_router,
        prefix="/api/metrics",
        tags=["Metrics"],
    )

    # registerUser messageroute
    app.include_router(
        user_messages_router,
        prefix="/api/messages",
        tags=["Messages"],
    )

    # registerConfiguration管理route
    app.include_router(
        config_router,
        prefix="/api/config",
        tags=["Config"],
    )

    # registerPersonality configurationroute
    app.include_router(
        personality_config_router,
        prefix="/api/personality",
        tags=["Personality Config"],
    )

    app.include_router(
        personality_presets_router,
        prefix="/api/personalities",
        tags=["Personality Presets"],
    )

    # register他人memoryroute
    app.include_router(
        others_router,
        prefix="/api/others",
        tags=["Others"],
    )

    # register Skills 管理route
    app.include_router(
        skills_router,
        tags=["Skills"],
    )

    app.include_router(
        timeline_router,
        prefix="/api/timeline",
        tags=["Timeline"],
    )

    app.include_router(
        plugins_router,
        prefix="/api/plugins",
        tags=["Plugins"],
    )
