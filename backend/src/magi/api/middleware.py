"""
API middleware for error handling, authentication, CORS, and request logging.
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import logging
import os

from ..plugins.i18n import set_current_language, DEFAULT_LANGUAGE, LANGUAGE_ALIASES

logger = logging.getLogger(__name__)


DESKTOP_SESSION_HEADER = "X-Magi-Session-Token"
QUIET_REQUEST_PATHS = {
    "/api/health",
    "/api/messages/sessions",
    "/api/config",
    "/api/config/",
    "/api/memory/models",
    "/api/timeline/sources/status",
    "/api/plugins",
    "/api/tools/config",
}
EXEMPT_PATH_PREFIXES = (
    "/static/",
)


def get_required_desktop_session_token() -> str | None:
    token = os.getenv("MAGI_DESKTOP_SESSION_TOKEN", "").strip()
    return token or None


class errorHandler(BaseHTTPMiddleware):
    """
    Global error handling middleware.

    Catches unhandled exceptions and returns a standardized error response.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.exception(f"Unhandled exception: {exc}")

            # Return统一errorformat
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
    """
    Authentication middleware.

    Validates JWT tokens (optional, mainly used in production).
    """

    # Paths that do not require authentication
    EXEMPT_PATHS = {
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/api/health",
        "/api/auth/login",
    }

    async def dispatch(self, request: Request, call_next: Callable):
        # Always allow CORS preflight requests
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        # Skip authentication for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        if request.url.path.startswith(EXEMPT_PATH_PREFIXES):
            return await call_next(request)

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

        # TODO: Implement JWT token validation
        # Authentication is currently skipped
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Request logging middleware.

    Records basic metadata and timing information for each request.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()
        should_log = request.url.path not in QUIET_REQUEST_PATHS

        # Log request metadata
        if should_log:
            logger.info(f"Request: {request.method} {request.url.path}")

        # Process request
        response = await call_next(request)

        # Calculate processing time
        process_time = time.time() - start_time
        response.headers["X-process-Time"] = str(process_time)

        # Log response metadata
        if should_log:
            logger.info(
                f"Response: {response.status_code} "
                f"took {process_time:.3f}s"
            )

        return response


class LanguageContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to set the language context for i18n.

    Extracts Accept-Language header and sets thread-local language for
    plugin translations.
    """

    def _normalize_language(self, lang: str | None) -> str:
        """Normalize language code to standard format."""
        if not lang:
            return DEFAULT_LANGUAGE

        # Handle multiple languages (e.g., "zh-CN,zh;q=0.9,en;q=0.8")
        primary_lang = lang.split(",")[0].strip().split(";")[0].strip()

        # Normalize using the same mapping as PluginI18n
        lang_lower = primary_lang.lower()
        return LANGUAGE_ALIASES.get(lang_lower, LANGUAGE_ALIASES.get(primary_lang, primary_lang))

    async def dispatch(self, request: Request, call_next: Callable):
        # Extract and normalize language from Accept-Language header
        accept_language = request.headers.get("Accept-Language")
        normalized_lang = self._normalize_language(accept_language)

        # Set the thread-local language context
        set_current_language(normalized_lang)

        try:
            response = await call_next(request)
            return response
        finally:
            # Clear language context after request
            set_current_language(None)


def add_cors_middleware(app):
    """
    Add CORS middleware to the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific domains
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
