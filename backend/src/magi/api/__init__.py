"""
API layer: FastAPI application and routes.
"""
from .middleware import ErrorHandler, AuthMiddleware
from .responses import SuccessResponse, ErrorResponse, PaginatedResponse


def create_app():
    """Lazy import to avoid heavy side effects during module import."""
    from .app import create_app as _create_app

    return _create_app()

__all__ = [
    "create_app",
    "ErrorHandler",
    "AuthMiddleware",
    "SuccessResponse",
    "ErrorResponse",
    "PaginatedResponse",
]
