"""
FastAPI应用主file

createandConfigurationFastAPI应用Instance
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
import logging
import json
import os
from pathlib import path

from .middleware import errorHandler, AuthMiddleware, RequestLoggingMiddleware, add_cors_middleware
from .responses import SuccessResponse
from .websocket import manager, broadcast_agent_update, broadcast_task_update, broadcast_metrics_update, broadcast_log
from ..agent import initialize_chat_agent, shutdown_chat_agent
from ..core.logger import configure_logging

logger = logging.getLogger(__name__)

# load .env file
try:
    from dotenv import load_dotenv
    # 优先load backend/.env（app.py 位于 backend/src/magi/api）
    candidate_paths = [
        path(__file__).resolve().parents[3] / ".env",  # backend/.env
        path.cwd() / ".env",                           # current工作directory
    ]
    loaded = False
    for env_path in candidate_paths:
        if env_path.exists():
            load_dotenv(env_path, override=False)
            logger.info(f"Loaded environment variables from {env_path}")
            loaded = True
            break
    if not loaded:
        load_dotenv(override=False)
        logger.info("No explicit .env path found, attempted default dotenv lookup")
except ImportError:
    logger.warning("python-dotenv not installed, .env file will not be loaded automatically")


def custom_openapi():
    """customOpenAPI schema"""
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


def create_app() -> FastAPI:
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
    )

    # SettingcustomOpenAPI
    app.openapi = custom_openapi

    # addmiddle件
    add_cors_middleware(app)
    app.add_middleware(errorHandler)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # registerroute
    _register_routes(app)

    # register生命periodevent
    @app.on_event("startup")
    async def startup_event():
        """应用启动时initializeChatAgent"""
        await initialize_chat_agent()

    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭时stopChatAgent"""
        await shutdown_chat_agent()

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

    # WebSocket端点
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket端点 - support房间subscribe"""
        # generation唯一的sessionid
        import uuid
        sid = str(uuid.uuid4())

        logger.info(f"New WebSocket connection attempt: {sid}")

        await manager.connect(sid, websocket)
        logger.info(f"WebSocket connection established: {sid}")

        try:
            while True:
                # receiveclientmessage
                try:
                    data = await websocket.receive_json()
                    logger.debug(f"Received WebSocket message from {sid}: {data}")
                except Exception as e:
                    logger.warning(f"Failed to receive JSON from {sid}: {e}")
                    # 尝试receive文本并parse
                    text_data = await websocket.receive_text()
                    logger.debug(f"Received text from {sid}: {text_data}")
                    try:
                        data = json.loads(text_data)
                    except:
                        logger.error(f"Invalid data format from {sid}")
                        continue

                # processsubscriberequest
                if data.get("type") == "subscribe":
                    channel = data.get("channel")
                    manager.join_room(sid, channel)
                    await websocket.send_json({
                        "type": "subscribed",
                        "channel": channel,
                        "sid": sid,
                    })
                    logger.info(f"Client {sid} subscribed to {channel}")

                elif data.get("type") == "unsubscribe":
                    channel = data.get("channel")
                    manager.leave_room(sid, channel)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "channel": channel,
                    })
                    logger.info(f"Client {sid} unsubscribed from {channel}")

                elif data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                    logger.debug(f"Ping from {sid}")

        except WebSocketDisconnect:
            logger.info(f"WebSocket {sid} disconnected (WebSocketDisconnect)")
            manager.disconnect(sid)
        except Exception as e:
            logger.error(f"WebSocket error for {sid}: {e}")
            manager.disconnect(sid)

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
        personality_router,
        others_router,
        skills_router,
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
        personality_router,
        prefix="/api/personality",
        tags=["Personality"],
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


# createglobal应用Instance
app = create_app()
