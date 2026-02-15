"""
FastAPI应用主文件

创建和配置FastAPI应用实例
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
import logging
import json
import os
from pathlib import Path

from .middleware import ErrorHandler, AuthMiddleware, RequestLoggingMiddleware, add_cors_middleware
from .responses import SuccessResponse
from .websocket import manager, broadcast_agent_update, broadcast_task_update, broadcast_metrics_update, broadcast_log
from ..agent import initialize_chat_agent, shutdown_chat_agent
from ..core.logger import configure_logging

logger = logging.getLogger(__name__)

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    # 优先加载 backend/.env（app.py 位于 backend/src/magi/api）
    candidate_paths = [
        Path(__file__).resolve().parents[3] / ".env",  # backend/.env
        Path.cwd() / ".env",                           # 当前工作目录
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
    """自定义OpenAPI schema"""
    if not app.openapi_schema:
        openapi_schema = get_openapi(
            title="Magi AI Agent Framework API",
            version="1.0.0",
            description="""
            ## Magi AI Agent Framework API

            Agent系统的RESTful API，提供Agent管理、任务管理、工具管理等功能。

            ### 功能特性
            - Agent管理（创建、查询、启动、停止）
            - 任务管理（创建、查询、重试）
            - 工具管理（列表、详情、测试）
            - 记忆管理（搜索、详情、删除）
            - 指标监控（性能、状态）

            ### 认证
            生产环境需要JWT token认证（开发环境已禁用）
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
    创建FastAPI应用实例

    Returns:
        FastAPI应用实例
    """
    # 配置日志（输出到运行时目录和终端）
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
        docs_url=None,  # 禁用默认文档，使用自定义路由
        redoc_url=None,
    )

    # 设置自定义OpenAPI
    app.openapi = custom_openapi

    # 添加中间件
    add_cors_middleware(app)
    app.add_middleware(ErrorHandler)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # 注册路由
    _register_routes(app)

    # 注册生命周期事件
    @app.on_event("startup")
    async def startup_event():
        """应用启动时初始化ChatAgent"""
        await initialize_chat_agent()

    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭时停止ChatAgent"""
        await shutdown_chat_agent()

    # 添加健康检查端点
    @app.get("/api/health", tags=["Health"])
    async def health_check():
        """健康检查"""
        return {
            "success": True,
            "message": "System is healthy",
            "data": {
                "status": "healthy",
                "version": "1.0.0",
            },
        }

    # 添加文档端点
    @app.get("/api/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        """自定义Swagger UI"""
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title="Magi API Docs",
        )

    @app.get("/api/openapi.json", include_in_schema=False)
    async def get_openapi_endpoint():
        """获取OpenAPI schema"""
        return app.openapi()

    # WebSocket端点
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket端点 - 支持房间订阅"""
        # 生成唯一的会话ID
        import uuid
        sid = str(uuid.uuid4())

        logger.info(f"New WebSocket connection attempt: {sid}")

        await manager.connect(sid, websocket)
        logger.info(f"WebSocket connection established: {sid}")

        try:
            while True:
                # 接收客户端消息
                try:
                    data = await websocket.receive_json()
                    logger.debug(f"Received WebSocket message from {sid}: {data}")
                except Exception as e:
                    logger.warning(f"Failed to receive JSON from {sid}: {e}")
                    # 尝试接收文本并解析
                    text_data = await websocket.receive_text()
                    logger.debug(f"Received text from {sid}: {text_data}")
                    try:
                        data = json.loads(text_data)
                    except:
                        logger.error(f"Invalid data format from {sid}")
                        continue

                # 处理订阅请求
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
    注册所有路由

    Args:
        app: FastAPI应用实例
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

    # 注册Agent管理路由
    app.include_router(
        agents_router,
        prefix="/api/agents",
        tags=["Agents"],
    )

    # 注册任务管理路由
    app.include_router(
        tasks_router,
        prefix="/api/tasks",
        tags=["Tasks"],
    )

    # 注册工具管理路由
    app.include_router(
        tools_router,
        prefix="/api/tools",
        tags=["Tools"],
    )

    # 注册记忆管理路由
    app.include_router(
        memory_router,
        prefix="/api/memory",
        tags=["Memory"],
    )

    # 注册指标监控路由
    app.include_router(
        metrics_router,
        prefix="/api/metrics",
        tags=["Metrics"],
    )

    # 注册用户消息路由
    app.include_router(
        user_messages_router,
        prefix="/api/messages",
        tags=["Messages"],
    )

    # 注册配置管理路由
    app.include_router(
        config_router,
        prefix="/api/config",
        tags=["Config"],
    )

    # 注册人格配置路由
    app.include_router(
        personality_router,
        prefix="/api/personality",
        tags=["Personality"],
    )

    # 注册他人记忆路由
    app.include_router(
        others_router,
        prefix="/api/others",
        tags=["Others"],
    )

    # 注册 Skills 管理路由
    app.include_router(
        skills_router,
        tags=["Skills"],
    )


# 创建全局应用实例
app = create_app()
