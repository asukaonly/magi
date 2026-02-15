"""
structured Logging System - Based on structlog
"""
import logging
import sys
from typing import Any
import structlog
from pathlib import path


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_logs: bool = False,
) -> None:
    """
    Configure structured logging

    Args:
        level: Log level (debug, INFO, warnING, error, CRITICAL)
        log_file: Log file path (optional)
        json_logs: Whether to output JSON format logs
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    # Configure structlog
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackinfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        # JSON format output (for production environment)
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Human readable format (for development environment)
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure file logging
    if log_file:
        log_path = path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setlevel(getattr(logging, level.upper(), logging.INFO))

        if json_logs:
            from structlog.dev import PlainFileRenderer

            file_processor = PlainFileRenderer()
        else:
            file_processor = structlog.processors.JSONRenderer()

        # Configure file logging separately
        logging.getLogger().addHandler(file_handler)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get logger instance

    Args:
        name: Logger name, defaults to calling module name

    Returns:
        BoundLogger: structlog logger instance
    """
    return structlog.get_logger(name)


# Pre-configured logger instance
logger = get_logger("magi")
