"""
FastAPI应用主file

createandConfigurationFastAPI应用Instance
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
import json
import os
from pathlib import Path

from .middleware import errorHandler, AuthMiddleware, RequestLoggingMiddleware, add_cors_middleware
from .responses import SuccessResponse
from .services import get_chat_read_service
from .websocket import manager, broadcast_agent_update, broadcast_task_update, broadcast_metrics_update, broadcast_log
from ..agent import initialize_chat_agent, shutdown_chat_agent
from ..core.logger import configure_logging, get_logger, Loggers
from ..events.events import Event, EventTypes

logger = get_logger(__name__, category="API")

# load .env file
try:
    from dotenv import load_dotenv
    # 优先load backend/.env（app.py 位于 backend/src/magi/api）
    candidate_paths = [
        Path(__file__).resolve().parents[3] / ".env",  # backend/.env
        Path.cwd() / ".env",                           # current工作directory
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
        from .routers.messages import get_message_bus

        message_bus = get_message_bus()
        if message_bus:
            async def _on_ai_response(event: Event):
                data = event.data if isinstance(event.data, dict) else {}
                user_id = str(data.get("user_id", "")).strip()
                if not user_id:
                    return
                await manager.broadcast("agent_response", data, room=f"user_{user_id}")

            sub_id = await message_bus.subscribe(
                EventTypes.AI_RESPONSE,
                _on_ai_response,
                propagation_mode="broadcast",
            )
            app.state.ai_response_subscription_id = sub_id
            logger.info(f"Subscribed AI_RESPONSE for websocket bridge | subscription_id={sub_id}")

    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭时stopChatAgent"""
        from .routers.messages import get_message_bus

        message_bus = get_message_bus()
        sub_id = getattr(app.state, "ai_response_subscription_id", None)
        if message_bus and sub_id:
            try:
                await message_bus.unsubscribe(sub_id)
            except Exception as exc:
                logger.warning(f"Failed to unsubscribe AI_RESPONSE bridge: {exc}")
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

                elif data.get("type") == "get_personality":
                    # 获取人格信息（名字、头像、问候语）
                    try:
                        from .routers.personality_config import get_current_personality
                        from ..memory.personality_loader import PersonalityLoader
                        from ..utils.runtime import get_runtime_paths
                        import random

                        current_name = get_current_personality()
                        runtime_paths = get_runtime_paths()
                        loader = PersonalityLoader(str(runtime_paths.personalities_dir))
                        config = loader.load(current_name)
                        greetings = config.cached_phrases.on_wake or config.cached_phrases.on_init
                        greeting = random.choice(greetings) if greetings else f"Hello, I am {config.name}."

                        # 处理 avatar URL
                        # 如果是文件名，转换成相对路径；emoji 或完整 URL 原样返回
                        avatar = config.avatar or ""
                        if avatar and not avatar.startswith(("http://", "https://", "/", "data:")):
                            # 检查是否是 emoji（Unicode 字符）
                            if len(avatar) <= 4 and any(ord(c) > 127 for c in avatar):
                                # 可能是 emoji，原样返回
                                pass
                            else:
                                # 是文件名，转换成相对路径，前端会拼接完整 URL
                                avatar = f"/static/avatars/{avatar}"

                        await websocket.send_json({
                            "type": "personality_info",
                            "data": {
                                "name": config.name,
                                "avatar": avatar,
                                "greeting": greeting,
                            },
                        })
                        logger.info(f"Sent personality info to {sid}: {config.name}")
                    except Exception as e:
                        logger.error(f"Failed to get personality info: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Failed to get personality info: {str(e)}",
                        })

                elif data.get("type") == "send_message":
                    # 通过 WebSocket 发送用户消息
                    try:
                        from ..agent import get_agent_runtime
                        from ..events.events import Event, EventTypes
                        import time

                        user_id = data.get("user_id", "web_user")
                        session_id = data.get("session_id")
                        message = data.get("message", "")

                        if not message:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Message is required",
                            })
                            continue

                        try:
                            get_agent_runtime()
                        except RuntimeError:
                            await websocket.send_json({
                                "type": "error",
                                "message": "AgentRuntime not initialized. Please set LLM_API_KEY.",
                            })
                            continue
                        read_service = get_chat_read_service()
                        resolved_session = session_id or read_service.get_current_session_id(user_id)

                        # 构建消息数据
                        message_data = {
                            "message": message,
                            "user_id": user_id,
                            "session_id": resolved_session,
                            "timestamp": time.time(),
                        }

                        # 发送到消息总线
                        from .routers.messages import get_message_bus
                        message_bus = get_message_bus()
                        if message_bus:
                            event = Event(
                                type=EventTypes.USER_MESSAGE,
                                data=message_data,
                                source="websocket",
                            )
                            await message_bus.publish(event)
                            logger.info(f"Message queued via WS | User: {user_id} | Session: {resolved_session}")

                        await websocket.send_json({
                            "type": "message_sent",
                            "data": {
                                "user_id": user_id,
                                "session_id": resolved_session,
                                "timestamp": time.time(),
                            },
                        })
                    except Exception as e:
                        logger.error(f"Failed to send message via WS: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Failed to send message: {str(e)}",
                        })

                elif data.get("type") == "get_current_session":
                    # 获取当前会话 ID
                    try:
                        user_id = data.get("user_id", "web_user")
                        read_service = get_chat_read_service()
                        session_id = read_service.get_current_session_id(user_id)

                        await websocket.send_json({
                            "type": "current_session",
                            "data": {
                                "user_id": user_id,
                                "session_id": session_id,
                            },
                        })
                    except RuntimeError:
                        # Agent 未初始化
                        await websocket.send_json({
                            "type": "current_session",
                            "data": {
                                "user_id": data.get("user_id", "web_user"),
                                "session_id": None,
                            },
                        })
                    except Exception as e:
                        logger.error(f"Failed to get current session: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Failed to get current session: {str(e)}",
                        })

                elif data.get("type") == "get_history":
                    # 获取历史记录
                    try:
                        user_id = data.get("user_id", "web_user")
                        session_id = data.get("session_id")

                        read_service = get_chat_read_service()
                        resolved_session = session_id or read_service.get_current_session_id(user_id)
                        history = read_service.get_conversation_history(user_id, resolved_session)

                        # 转换为前端期望的格式
                        import time
                        messages = []
                        for msg in history:
                            messages.append({
                                "role": msg["role"],
                                "content": msg["content"],
                                "timestamp": int(msg.get("timestamp", time.time())),
                            })

                        await websocket.send_json({
                            "type": "history",
                            "data": {
                                "user_id": user_id,
                                "session_id": resolved_session,
                                "messages": messages,
                                "count": len(messages),
                            },
                        })
                    except RuntimeError:
                        # Agent 未初始化
                        await websocket.send_json({
                            "type": "history",
                            "data": {
                                "user_id": data.get("user_id", "web_user"),
                                "session_id": data.get("session_id"),
                                "messages": [],
                                "count": 0,
                            },
                        })
                    except Exception as e:
                        logger.error(f"Failed to get history: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Failed to get history: {str(e)}",
                        })

        except WebSocketDisconnect:
            logger.info(f"WebSocket {sid} disconnected (WebSocketDisconnect)")
            manager.disconnect(sid)
        except Exception as e:
            logger.error(f"WebSocket error for {sid}: {e}")
            manager.disconnect(sid)

    # 挂载静态文件目录（头像）
    avatar_dir = Path(__file__).resolve().parents[3] / "personalities" / "avatar"
    if avatar_dir.exists():
        app.mount("/static/avatars", StaticFiles(directory=str(avatar_dir)), name="avatars")
        logger.info(f"Avatar static files mounted: {avatar_dir}")

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


# createglobal应用Instance
app = create_app()
