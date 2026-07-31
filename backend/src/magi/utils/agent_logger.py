"""
Agent logging configuration.

Provides dedicated logging for agent processing chains.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from .log_redaction import RedactingFormatter

AGENT_CHAIN_LOGGER_BASE = "magi.agent.chain"


def _get_agent_log_file() -> str:
    """Get agent log file path (uses runtime directory)."""
    from ..utils.runtime import get_runtime_paths
    runtime_paths = get_runtime_paths()
    return str(runtime_paths.logs_dir / 'agent_chain.log')


def setup_agent_logger() -> logging.Logger:
    """
    Configure agent-specific logger.

    Returns:
        Agent-specific logger instance.
    """
    # Create logger
    agent_logger = logging.getLogger(AGENT_CHAIN_LOGGER_BASE)
    agent_logger.setLevel(logging.DEBUG)

    # Avoid adding duplicate handlers
    if agent_logger.handlers:
        return agent_logger

    # Get log file path
    agent_log_file = _get_agent_log_file()
    # Ensure directory exists
    os.makedirs(os.path.dirname(agent_log_file), exist_ok=True)

    # File handler with automatic rotation
    file_handler = RotatingFileHandler(
        agent_log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        RedactingFormatter(
            fmt="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    # Add handlers
    agent_logger.addHandler(file_handler)

    return agent_logger


# Global agent logger instance
agent_logger = setup_agent_logger()


def get_agent_logger(name: str | None = None) -> logging.Logger:
    """
    Get agent logger instance.

    Args:
        name: Logger name (optional, for sub-loggers).

    Returns:
        Agent logger instance.
    """
    if name:
        return logging.getLogger(f"{AGENT_CHAIN_LOGGER_BASE}.{name}")
    return agent_logger


# Agent chain logging helpers
def log_chain_start(logger: logging.Logger, chain_id: str, message: str) -> None:
    """Log chain start."""
    logger.info(f"{'='*60}")
    logger.info(f"[chain:{chain_id}] start | {message}")
    logger.info(f"{'='*60}")


def log_chain_step(logger: logging.Logger, chain_id: str, step: str, message: str, level: str = "INFO") -> None:
    """Log chain step."""
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(f"[chain:{chain_id}] [{step}] {message}")


def log_chain_end(logger: logging.Logger, chain_id: str, message: str, success: bool = True) -> None:
    """Log chain end."""
    status = "✅ SUCCESS" if success else "❌ FAILED"
    logger.info(f"[chain:{chain_id}] end {status} | {message}")
    logger.info(f"{'='*60}")
