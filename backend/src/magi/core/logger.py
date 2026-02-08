"""
结构化日志系统 - 基于structlog
"""
import logging
import sys
from typing import Any
import structlog
from pathlib import Path


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_logs: bool = False,
) -> None:
    """
    配置结构化日志

    Args:
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_file: 日志文件路径（可选）
        json_logs: 是否输出JSON格式日志
    """
    # 配置标准库logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    # 配置structlog
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        # JSON格式输出（用于生产环境）
        processors.append(structlog.processors.JSONRenderer())
    else:
        # 人类可读格式（用于开发环境）
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

    # 配置文件日志
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))

        if json_logs:
            from structlog.dev import PlainFileRenderer

            file_processor = PlainFileRenderer()
        else:
            file_processor = structlog.processors.JSONRenderer()

        # 为文件日志单独配置
        logging.getLogger().addHandler(file_handler)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    获取logger实例

    Args:
        name: logger名称，默认为调用模块名

    Returns:
        BoundLogger: structlog logger实例
    """
    return structlog.get_logger(name)


# 预配置的logger实例
logger = get_logger("magi")
