"""
API中间件

包含错误处理、认证、CORS等中间件
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import logging

logger = logging.getLogger(__name__)


class ErrorHandler(BaseHTTPMiddleware):
    """
    全局错误处理中间件

    捕获所有异常并返回统一格式的错误响应
    """

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.exception(f"Unhandled exception: {exc}")

            # 返回统一错误格式
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "message": "Internal server error",
                    "error_code": "INTERNAL_ERROR",
                    "details": str(exc) if logger.isEnabledFor(logging.DEBUG) else None,
                },
            )


class AuthMiddleware(BaseHTTPMiddleware):
    """
    认证中间件

    验证JWT token（可选，用于生产环境）
    """

    # 不需要认证的路径
    EXEMPT_PATHS = {
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/api/health",
        "/api/auth/login",
    }

    async def dispatch(self, request: Request, call_next: Callable):
        # 检查是否豁免认证
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # TODO: 实现JWT token验证
        # 目前暂时跳过认证
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    请求日志中间件

    记录所有请求的详细信息
    """

    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()

        # 记录请求
        logger.info(f"Request: {request.method} {request.url.path}")

        # 处理请求
        response = await call_next(request)

        # 计算处理时间
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)

        # 记录响应
        logger.info(
            f"Response: {response.status_code} "
            f"took {process_time:.3f}s"
        )

        return response


def add_cors_middleware(app):
    """
    添加CORS中间件

    Args:
        app: FastAPI应用实例
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
