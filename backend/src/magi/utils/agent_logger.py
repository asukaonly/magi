"""
Agent日志配置

为Agent处理链路提供专门的日志记录
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


# Agent专用日志目录
AGENT_LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs')
os.makedirs(AGENT_LOG_DIR, exist_ok=True)

# Agent日志文件路径
AGENT_LOG_FILE = os.path.join(AGENT_LOG_DIR, 'agent_chain.log')


class AgentFormatter(logging.Formatter):
    """Agent日志格式化器 - 添加时间戳和链路追踪信息"""

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_agent_logger():
    """
    配置Agent专用logger

    Returns:
        logging.Logger: Agent专用logger实例
    """
    # 创建logger
    agent_logger = logging.getLogger('magi.agent')
    agent_logger.setLevel(logging.DEBUG)

    # 防止重复添加handler
    if agent_logger.handlers:
        return agent_logger

    # 文件handler - 自动轮转
    file_handler = RotatingFileHandler(
        AGENT_LOG_FILE,
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

    # 添加handler
    agent_logger.addHandler(file_handler)
    agent_logger.addHandler(console_handler)

    return agent_logger


# 全局Agent logger实例
agent_logger = setup_agent_logger()


def get_agent_logger(name: str = None) -> logging.Logger:
    """
    获取Agent logger实例

    Args:
        name: logger名称（可选）

    Returns:
        logging.Logger: Agent logger实例
    """
    if name:
        return logging.getLogger(f'magi.agent.{name}')
    return agent_logger


# Agent链路日志辅助函数
def log_chain_start(logger: logging.Logger, chain_id: str, message: str):
    """记录链路开始"""
    logger.info(f"{'='*60}")
    logger.info(f"[CHAIN:{chain_id}] START | {message}")
    logger.info(f"{'='*60}")


def log_chain_step(logger: logging.Logger, chain_id: str, step: str, message: str, level: str = "INFO"):
    """记录链路步骤"""
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(f"[CHAIN:{chain_id}] [{step}] {message}")


def log_chain_end(logger: logging.Logger, chain_id: str, message: str, success: bool = True):
    """记录链路结束"""
    status = "✅ SUCCESS" if success else "❌ FAILED"
    logger.info(f"[CHAIN:{chain_id}] END {status} | {message}")
    logger.info(f"{'='*60}")
