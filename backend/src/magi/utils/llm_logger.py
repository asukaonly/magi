"""
LLM call logging configuration.

Logs LLM request prompts and response outputs.
"""
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from .safe_logging import SafeStreamHandler

LLM_CALL_LOGGER_BASE = "magi.llm.calls"


def _get_llm_log_file() -> str:
    """Get LLM log file path (uses runtime directory)."""
    from ..utils.runtime import get_runtime_paths
    runtime_paths = get_runtime_paths()
    return str(runtime_paths.logs_dir / 'llm_calls.log')


def setup_llm_logger() -> logging.Logger:
    """
    Configure LLM-specific logger.

    Returns:
        LLM-specific logger instance.
    """
    # Create logger
    llm_logger = logging.getLogger(LLM_CALL_LOGGER_BASE)
    llm_logger.setLevel(logging.DEBUG)
    llm_logger.propagate = False

    # Avoid adding duplicate handlers
    if llm_logger.handlers:
        return llm_logger

    # Get log file path
    llm_log_file = _get_llm_log_file()
    # Ensure directory exists
    os.makedirs(os.path.dirname(llm_log_file), exist_ok=True)

    # File handler with automatic rotation
    file_handler = RotatingFileHandler(
        llm_log_file,
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    # Add handlers
    llm_logger.addHandler(file_handler)
    llm_logger.addHandler(console_handler)

    return llm_logger


# Global LLM logger instance
llm_logger = setup_llm_logger()


def get_llm_logger(name: str | None = None) -> logging.Logger:
    """
    Get LLM logger instance.

    Args:
        name: Logger name (optional, for sub-loggers).

    Returns:
        LLM logger instance.
    """
    if name:
        return logging.getLogger(f"{LLM_CALL_LOGGER_BASE}.{name}")
    return llm_logger


def truncate_text(text: str, max_length: int = 5000) -> str:
    """
    Truncate text that exceeds max length.

    Args:
        text: Original text.
        max_length: Maximum character length.

    Returns:
        Truncated text.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"... (truncated, total {len(text)} chars)"


def _try_pretty_json(text: str) -> str:
    """Pretty-print JSON strings for human-readable logs when possible."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return text
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return text
    return json.dumps(parsed, ensure_ascii=False, indent=2).replace("\\n", "\n")


def _format_message_content(role: str, content: Any) -> str:
    """Render message content for logs with special handling for tool payloads."""
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False, indent=2)

    normalized = "" if content is None else str(content)
    if role == "tool":
        return _try_pretty_json(normalized)
    return normalized


def _format_log_text(text: Any, max_length: int, truncate: bool) -> str:
    """Format text for logging with optional truncation."""
    if not isinstance(text, str):
        text = str(text)
    if not truncate:
        return text
    return truncate_text(text, max_length)


def _log_system_prompt(
    logger: logging.Logger,
    system_prompt: str,
    max_length: int,
    truncate: bool,
    cache_boundary: Optional[str],
) -> None:
    """Log the system prompt, split at the cache boundary when present.

    The provider bridge splits the rendered system prompt at ``cache_boundary``:
    the head is sent as the cached ``system`` field (with a cache_control
    marker), and the per-turn tail is moved into the last user message — it is
    NOT in ``system`` on the wire. Logging the two parts separately mirrors
    what's actually sent and makes it obvious which bytes are cacheable vs.
    recomputed each turn. The boundary marker itself is stripped before sending.

    ``cache_boundary`` is passed in (rather than imported) so this low-level
    logging module stays free of higher-layer imports.
    """
    if not cache_boundary or cache_boundary not in system_prompt:
        logger.debug(f"System Prompt:\n{_format_log_text(system_prompt, max_length, truncate)}")
        return

    head, _, tail = system_prompt.partition(cache_boundary)
    head = head.rstrip("\n")
    tail = tail.lstrip("\n")
    logger.debug(
        f"System Prompt [cacheable head — sent as `system` with cache_control]:\n"
        f"{_format_log_text(head, max_length, truncate)}"
    )
    logger.debug("-" * 40)
    logger.debug(
        f"System Prompt [per-turn tail — injected before the last user message, "
        f"NOT in `system` on the wire]:\n{_format_log_text(tail, max_length, truncate)}"
    )


def log_llm_request(
    logger: logging.Logger,
    request_id: str,
    model: str,
    system_prompt: str,
    messages: list,
    truncate: bool = False,
    system_prompt_max_length: int = 2000,
    message_max_length: int = 1000,
    cache_boundary: Optional[str] = None,
    **kwargs
):
    """
    Log LLM request.

    Args:
        logger: Logger instance.
        request_id: Request ID.
        model: Model name.
        system_prompt: System prompt.
        messages: Message list.
        cache_boundary: Internal cache-boundary marker; when present in the
            system prompt, the log shows the cacheable head and per-turn tail
            separately (mirrors what the provider bridge sends).
        **kwargs: Other parameters.
    """
    logger.debug("=" * 80)
    logger.debug(f"LLM_REQUEST [{request_id}] | Model: {model}")
    logger.debug("-" * 80)
    _log_system_prompt(logger, system_prompt, system_prompt_max_length, truncate, cache_boundary)
    logger.debug("-" * 80)
    logger.debug("Messages:")
    for i, msg in enumerate(messages):
        rendered_content = _format_message_content(
            str(msg.get("role", "")),
            msg.get("content", ""),
        )
        logger.debug(
            f"  [{i}] {msg.get('role')}: "
            f"{_format_log_text(rendered_content, message_max_length, truncate)}"
        )
    if kwargs:
        logger.debug(f"Parameters: {kwargs}")
    logger.debug("=" * 80)


def log_llm_response(
    logger: logging.Logger,
    request_id: str,
    response: str,
    success: bool = True,
    error: Optional[str] = None,
    duration_ms: Optional[int] = None,
    truncate: bool = True,
    response_max_length: int = 3000,
    **metadata
):
    """
    Log LLM response.

    Args:
        logger: Logger instance.
        request_id: Request ID.
        response: Response content.
        success: Whether the call succeeded.
        error: Error message if failed.
        duration_ms: Duration in milliseconds.
        **metadata: Additional metadata.
    """
    status = "SUCCESS" if success else "FAILED"
    logger.debug("=" * 80)
    logger.debug(f"LLM_RESPONSE [{request_id}] | {status}")
    if duration_ms:
        logger.debug(f"Duration: {duration_ms}ms")
    if error:
        logger.debug(f"error: {error}")
    if metadata:
        logger.debug(f"Metadata: {metadata}")
    logger.debug("-" * 80)
    if success and response:
        logger.debug(f"Response:\n{_format_log_text(_try_pretty_json(response), response_max_length, truncate)}")
    logger.debug("=" * 80)
