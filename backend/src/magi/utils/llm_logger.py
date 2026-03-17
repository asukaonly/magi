"""
LLM call logging configuration.

Logs LLM request prompts and response outputs.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

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

    # Add handler
    llm_logger.addHandler(file_handler)

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


def _format_log_text(text: str, max_length: int, truncate: bool) -> str:
    """Format text for logging with optional truncation."""
    if not truncate:
        return text
    return truncate_text(text, max_length)


def log_llm_request(
    logger: logging.Logger,
    request_id: str,
    model: str,
    system_prompt: str,
    messages: list,
    truncate: bool = True,
    system_prompt_max_length: int = 2000,
    message_max_length: int = 1000,
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
        **kwargs: Other parameters.
    """
    logger.debug("=" * 80)
    logger.debug(f"LLM_REQUEST [{request_id}] | Model: {model}")
    logger.debug("-" * 80)
    logger.debug(f"System Prompt:\n{_format_log_text(system_prompt, system_prompt_max_length, truncate)}")
    logger.debug("-" * 80)
    logger.debug("Messages:")
    for i, msg in enumerate(messages):
        logger.debug(
            f"  [{i}] {msg.get('role')}: "
            f"{_format_log_text(msg.get('content', ''), message_max_length, truncate)}"
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
        logger.debug(f"Response:\n{_format_log_text(response, response_max_length, truncate)}")
    logger.debug("=" * 80)
