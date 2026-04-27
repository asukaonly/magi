"""Lightweight logging helpers for Magi plugins.

External plugins should not need the backend's structlog setup just to emit
basic logs during development or when running inside the host. When Magi has
already configured logging, these helpers reuse the host configuration.
"""
from __future__ import annotations

import logging

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"


def configure_basic_logging(level: int | str = logging.INFO) -> None:
    """Configure a minimal stdlib logging setup when no handlers exist."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a stdlib logger for plugin code.

    The helper intentionally stays lightweight and backend-agnostic. If the host
    has not configured logging yet, it installs a minimal default formatter so
    plugin logs remain visible during local development.
    """
    configure_basic_logging()
    return logging.getLogger(name or "magi.plugin")


__all__ = ["configure_basic_logging", "get_logger"]