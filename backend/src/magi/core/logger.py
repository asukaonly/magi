"""
structured Logging System - Based on structlog
"""
import logging
import sys
from typing import Any
import structlog
from pathlib import Path


def _format_log_event(logger, method_name, event_dict):
    """Custom formatter for plain text output."""
    # Extract fields
    timestamp = event_dict.pop("timestamp", "")
    level = str(event_dict.pop("level", "")).upper().ljust(5)
    logger_name = event_dict.pop("logger", event_dict.pop("logger_name", ""))
    event = event_dict.pop("event", "")

    # Build extra fields string
    extra = []
    for key, value in event_dict.items():
        if isinstance(value, str):
            extra.append(f"{key}='{value}'")
        else:
            extra.append(f"{key}={value}")

    extra_str = " ".join(extra)
    if extra_str:
        extra_str = " " + extra_str

    # Format: timestamp [LEVEL] [logger] event extra
    return f"{timestamp} [{level}] [{logger_name}] {event}{extra_str}"


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_logs: bool = False,
) -> None:
    """
    Configure structured logging with unified plain text format.

    Format: TIMESTAMP [LEVEL] [MODULE] message key='value' key2=value2

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Log file path (optional)
        json_logs: Whether to output JSON format logs
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Set log levels for noisy libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    # Shared processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]

    if json_logs:
        # JSON format output (for production environment)
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Plain text format (no colors)
        processors = shared_processors + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _format_log_event,
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure file logging
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        logging.getLogger().addHandler(file_handler)


def get_logger(name: str | None = None, category: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get logger instance with optional business category.

    Args:
        name: Logger name, defaults to calling module name
        category: Business category (e.g., "api", "agent", "memory", "ws")

    Returns:
        BoundLogger: structlog logger instance
    """
    log = structlog.get_logger(name)
    if category:
        log = log.bind(category=category)
    return log


# Pre-configured logger instances by category
class Loggers:
    """Pre-configured logger instances for different modules."""

    @staticmethod
    def api():
        return get_logger("magi.api", category="API")

    @staticmethod
    def agent():
        return get_logger("magi.agent", category="AGENT")

    @staticmethod
    def memory():
        return get_logger("magi.memory", category="MEMORY")

    @staticmethod
    def ws():
        return get_logger("magi.ws", category="WS")

    @staticmethod
    def perception():
        return get_logger("magi.perception", category="PERCEPTION")

    @staticmethod
    def llm():
        return get_logger("magi.llm", category="LLM")


# Default logger
logger = get_logger("magi")
