"""
structured Logging System - Based on structlog
"""

from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import sys
from typing import Any
import structlog
from pathlib import Path

_LOGGING_CONFIGURED = False
DEFAULT_LOG_FILE_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_LOG_FILE_BACKUP_COUNT = 10


def _format_log_event(logger, method_name, event_dict):
    """Custom formatter for plain text output."""
    # Extract fields
    timestamp = event_dict.pop("timestamp", "")
    level = str(event_dict.pop("level", "")).upper()
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


def _add_timestamp_millis(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Attach local timestamp with millisecond precision."""
    now = datetime.now().astimezone()
    event_dict["timestamp"] = f"{now.strftime('%Y-%m-%d %H:%M:%S')}.{now.microsecond // 1000:03d}"
    return event_dict


def _build_processor_formatter(
    *,
    shared_processors: list[Any],
    json_logs: bool,
) -> structlog.stdlib.ProcessorFormatter:
    """Build a formatter that handles both structlog and stdlib logging."""
    if json_logs:
        processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _format_log_event,
        ]

    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=processors,
    )


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
    global _LOGGING_CONFIGURED
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        _add_timestamp_millis,
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(log_level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(
        _build_processor_formatter(shared_processors=shared_processors, json_logs=json_logs)
    )
    root_logger.addHandler(stream_handler)

    if json_logs:
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
    else:
        processors = shared_processors + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
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

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=DEFAULT_LOG_FILE_MAX_BYTES,
            backupCount=DEFAULT_LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(
            _build_processor_formatter(shared_processors=shared_processors, json_logs=json_logs)
        )
        root_logger.addHandler(file_handler)

    # Set log levels for noisy libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    _LOGGING_CONFIGURED = True


def get_logger(
    name: str | None = None, category: str | None = None
) -> structlog.stdlib.BoundLogger:
    """
    Get logger instance with optional business category.

    Args:
        name: Logger name, defaults to calling module name
        category: Business category (e.g., "api", "agent", "memory", "ws")

    Returns:
        BoundLogger: structlog logger instance
    """
    if not _LOGGING_CONFIGURED:
        configure_logging(level="INFO", json_logs=False)

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
