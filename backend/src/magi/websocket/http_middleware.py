"""HTTP transport middleware for the connection and transport layer."""

from __future__ import annotations

import logging
import time
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from ..config import get_config
from ..plugins.i18n import DEFAULT_LANGUAGE, LANGUAGE_ALIASES, set_current_language

logger = logging.getLogger(__name__)

DESKTOP_SESSION_HEADER = "X-Magi-Session-Token"
QUIET_REQUEST_PATHS = {
    "/api/health",
    "/api/ready",
    "/api/messages/sessions",
    "/api/config",
    "/api/config/",
    "/api/memory/models",
    "/api/timeline/sources/status",
    "/api/plugins",
    "/api/tools/config",
}
EXEMPT_PATH_PREFIXES = ("/static/",)


def get_required_desktop_session_token() -> str | None:
    """Return the configured desktop session token when present."""
    token = str(get_config().server.desktop_session_token or "").strip()
    return token or None


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
                    "message": "Internal server error",
                    "error_code": "internal_error",
                    "details": str(exc) if logger.isEnabledFor(logging.DEBUG) else None,
                },
            )


class AuthMiddleware(BaseHTTPMiddleware):
    """Transport-level auth middleware."""

    EXEMPT_PATHS = {
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/api/health",
        "/api/ready",
        "/api/auth/login",
    }

    async def dispatch(self, request: Request, call_next: Callable):
        if request.method.upper() == "OPTIONS":
            return await _call_next_or_handle_client_disconnect(request, call_next)

        if request.url.path in self.EXEMPT_PATHS:
            return await _call_next_or_handle_client_disconnect(request, call_next)

        if request.url.path.startswith(EXEMPT_PATH_PREFIXES):
            return await _call_next_or_handle_client_disconnect(request, call_next)

        desktop_token = get_required_desktop_session_token()
        if desktop_token:
            provided = request.headers.get(DESKTOP_SESSION_HEADER, "").strip()
            if provided != desktop_token:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "success": False,
                        "message": "Desktop session token is invalid",
                        "error_code": "desktop_auth_failed",
                    },
                )

        return await _call_next_or_handle_client_disconnect(request, call_next)


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
    """Set the language context for plugin i18n."""

    def _normalize_language(self, lang: str | None) -> str:
        if not lang:
            return DEFAULT_LANGUAGE

        primary_lang = lang.split(",")[0].strip().split(";")[0].strip()
        lang_lower = primary_lang.lower()
        return LANGUAGE_ALIASES.get(lang_lower, LANGUAGE_ALIASES.get(primary_lang, primary_lang))

    async def dispatch(self, request: Request, call_next: Callable):
        accept_language = request.headers.get("Accept-Language")
        normalized_lang = self._normalize_language(accept_language)
        set_current_language(normalized_lang)

        try:
            return await _call_next_or_handle_client_disconnect(request, call_next)
        finally:
            set_current_language(None)


def add_cors_middleware(app) -> None:
    """Add CORS middleware to the FastAPI application."""
    config = get_config()
    origins = getattr(getattr(config, "server", None), "cors_origins", ["*"])
    allow_creds = "*" not in origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )
