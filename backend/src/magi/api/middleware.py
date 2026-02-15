"""
APImiddle件

containserrorprocess、authentication、CORS等middle件
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import logging

logger = logging.getLogger(__name__)


class errorHandler(BaseHTTPMiddleware):
    """
    globalerrorprocessing间件

    allException并Return统一format的errorresponse
    """

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.exception(f"Unhandled exception: {exc}")

            # Return统一errorformat
            return JSONResponse(
                status_code=status.HTTP_500_internal_server_error,
                content={
                    "success": False,
                    "message": "Internal server error",
                    "error_code": "internal_error",
                    "details": str(exc) if logger.isEnabledFor(logging.debug) else None,
                },
            )


class AuthMiddleware(BaseHTTPMiddleware):
    """
    authenticationmiddle件

    ValidateJWT token（optional，用于生产环境）
    """

    # 不需要authentication的path
    EXEMPT_pathS = {
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/api/health",
        "/api/auth/login",
    }

    async def dispatch(self, request: Request, call_next: Callable):
        # checkis notttt豁免authentication
        if request.url.path in self.EXEMPT_pathS:
            return await call_next(request)

        # TODO: ImplementationJWT tokenValidate
        # 目前暂时跳过authentication
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    requestLogmiddle件

    recordallrequest的详细info
    """

    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()

        # recordrequest
        logger.info(f"Request: {request.method} {request.url.path}")

        # processrequest
        response = await call_next(request)

        # calculateprocess时间
        process_time = time.time() - start_time
        response.headers["X-process-Time"] = str(process_time)

        # recordresponse
        logger.info(
            f"Response: {response.status_code} "
            f"took {process_time:.3f}s"
        )

        return response


def add_cors_middleware(app):
    """
    addCORSmiddle件

    Args:
        app: FastAPI应用Instance
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应limitation具体domain
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
