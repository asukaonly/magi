"""
API层 - FastAPI应用androute
"""
from .middleware import errorHandler, AuthMiddleware
from .responses import SuccessResponse, errorResponse, PaginatedResponse


def create_app():
    """Lazy import to avoid heavy side effects during module import."""
    from .app import create_app as _create_app

    return _create_app()

__all__ = [
    "create_app",
    "errorHandler",
    "AuthMiddleware",
    "SuccessResponse",
    "errorResponse",
    "PaginatedResponse",
]
