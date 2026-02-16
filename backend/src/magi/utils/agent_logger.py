"""
AgentLogConfiguration

为Agentprocess链路提供专门的Logrecord
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


def _get_agent_log_file():
    """getAgentLogfilepath（使用run时directory）"""
    from ..utils.runtime import get_runtime_paths
    runtime_paths = get_runtime_paths()
    return str(runtime_paths.logs_dir / 'agent_chain.log')


class AgentFormatter(logging.Formatter):
    """AgentLogformat化器 - addtimestampand链路追踪info"""

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_agent_logger():
    """
    ConfigurationAgent专用logger

    Returns:
        logging.Logger: Agent专用loggerInstance
    """
    # createlogger
    agent_logger = logging.getLogger('magi.agent')
    agent_logger.setLevel(logging.DEBUG)

    # 防止重复addhandler
    if agent_logger.handlers:
        return agent_logger

    # getLogfilepath
    agent_log_file = _get_agent_log_file()
    # 确保directoryexists
    os.makedirs(os.path.dirname(agent_log_file), exist_ok=True)

    # filehandler - 自动轮转
    file_handler = RotatingFileHandler(
        agent_log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(AgentFormatter())

    # 控制台handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(AgentFormatter())

    # addhandler
    agent_logger.addHandler(file_handler)
    agent_logger.addHandler(console_handler)

    return agent_logger


# globalAgent loggerInstance
agent_logger = setup_agent_logger()


def get_agent_logger(name: str = None) -> logging.Logger:
    """
    getAgent loggerInstance

    Args:
        name: loggerName（optional）

    Returns:
        logging.Logger: Agent loggerInstance
    """
    if name:
        return logging.getLogger(f'magi.agent.{name}')
    return agent_logger


# Agent链路LogHelper Functions
def log_chain_start(logger: logging.Logger, chain_id: str, message: str):
    """record链路Start"""
    logger.info(f"{'='*60}")
    logger.info(f"[chain:{chain_id}] start | {message}")
    logger.info(f"{'='*60}")


def log_chain_step(logger: logging.Logger, chain_id: str, step: str, message: str, level: str = "INFO"):
    """record链路step"""
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(f"[chain:{chain_id}] [{step}] {message}")


def log_chain_end(logger: logging.Logger, chain_id: str, message: str, success: bool = True):
    """record链路End"""
    status = "✅ SUCCESS" if success else "❌ failED"
    logger.info(f"[chain:{chain_id}] end {status} | {message}")
    logger.info(f"{'='*60}")
