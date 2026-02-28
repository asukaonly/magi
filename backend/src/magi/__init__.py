"""Magi package public entrypoints."""

def create_backend_app():
    from .backend_app import create_backend_app as _create_backend_app
    return _create_backend_app()

__all__ = [
    "create_backend_app",
]
