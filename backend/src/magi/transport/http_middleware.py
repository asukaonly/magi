"""HTTP transport middleware for the IPC-only Python worker."""

from __future__ import annotations

import logging
import time
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..i18n import DEFAULT_LANGUAGE, normalize_language, set_current_language, t
from ..plugins.i18n import set_current_language as set_plugin_current_language

logger = logging.getLogger(__name__)

QUIET_REQUEST_PATHS = {
    "/api/health",
    "/api/ready",
    "/api/messages/sessions",
    "/api/config",
    "/api/config/",
    "/api/memory/models",
    "/api/sources/status",
    "/api/plugins",
    "/api/tools/config",
}


async def _call_next_or_handle_client_disconnect(
    request: Request,
    call_next: Callable,
) -> Response:
    """Treat client disconnects as a completed empty response instead of an error."""
    try:
        return await call_next(request)
    except RuntimeError as exc:
        if str(exc) == "No response returned." and await request.is_disconnected():
            logger.debug("Client disconnected before response completed", path=request.url.path)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        raise


class ErrorHandler(BaseHTTPMiddleware):
    """Global error handling middleware."""

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            return await _call_next_or_handle_client_disconnect(request, call_next)
        except Exception as exc:
            logger.exception(f"Unhandled exception: {exc}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "message": t(
                        "errors.internal_server_error",
                        language=request.headers.get("Accept-Language"),
                        fallback="Internal server error",
                    ),
                    "error_code": "internal_error",
                    "details": str(exc) if logger.isEnabledFor(logging.DEBUG) else None,
                },
            )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Request logging middleware."""

    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()
        should_log = request.url.path not in QUIET_REQUEST_PATHS

        if should_log:
            logger.debug(f"Request: {request.method} {request.url.path}")

        response = await _call_next_or_handle_client_disconnect(request, call_next)
        process_time = time.time() - start_time
        response.headers["X-process-Time"] = str(process_time)

        if should_log:
            logger.debug(f"Response: {response.status_code} took {process_time:.3f}s")

        return response


class LanguageContextMiddleware(BaseHTTPMiddleware):
    """Set request language contexts for backend and plugin i18n."""

    def _normalize_language(self, lang: str | None) -> str:
        return normalize_language(lang, default=DEFAULT_LANGUAGE)

    async def dispatch(self, request: Request, call_next: Callable):
        accept_language = request.headers.get("Accept-Language")
        normalized_lang = self._normalize_language(accept_language)
        set_current_language(normalized_lang)
        set_plugin_current_language(normalized_lang)

        try:
            return await _call_next_or_handle_client_disconnect(request, call_next)
        finally:
            set_current_language(None)
            set_plugin_current_language(None)
