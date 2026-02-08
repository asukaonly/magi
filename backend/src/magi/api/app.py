"""
FastAPI应用主文件

创建和配置FastAPI应用实例
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
import logging
import json

from .middleware import ErrorHandler, AuthMiddleware, RequestLoggingMiddleware, add_cors_middleware
from .responses import SuccessResponse
from .websocket import manager, broadcast_agent_update, broadcast_task_update, broadcast_metrics_update, broadcast_log

logger = logging.getLogger(__name__)


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
        """WebSocket端点"""
        await manager.connect(websocket)
        try:
            while True:
                # 接收客户端消息
                data = await websocket.receive_json()
                logger.debug(f"Received WebSocket message: {data}")

                # 处理订阅请求
                if data.get("type") == "subscribe":
                    # 订阅特定频道的消息
                    await websocket.send_json({
                        "type": "subscribed",
                        "channel": data.get("channel"),
                    })
                elif data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            manager.disconnect(websocket)

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


# 创建全局应用实例
app = create_app()
