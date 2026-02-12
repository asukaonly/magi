"""
LLM调用日志配置

专门记录LLM调用的prompt和输出结果
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


def _get_llm_log_file():
    """获取LLM日志文件路径（使用运行时目录）"""
    from ..utils.runtime import get_runtime_paths
    runtime_paths = get_runtime_paths()
    return str(runtime_paths.logs_dir / 'llm_calls.log')


class LLMFormatter(logging.Formatter):
    """LLM日志格式化器 - 结构化日志格式"""

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_llm_logger():
    """
    配置LLM专用logger

    Returns:
        logging.Logger: LLM专用logger实例
    """
    # 创建logger
    llm_logger = logging.getLogger('magi.llm')
    llm_logger.setLevel(logging.DEBUG)

    # 防止重复添加handler
    if llm_logger.handlers:
        return llm_logger

    # 获取日志文件路径
    llm_log_file = _get_llm_log_file()
    # 确保目录存在
    os.makedirs(os.path.dirname(llm_log_file), exist_ok=True)

    # 文件handler - 自动轮转
    file_handler = RotatingFileHandler(
        llm_log_file,
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(LLMFormatter())

    # 添加handler
    llm_logger.addHandler(file_handler)

    return llm_logger


# 全局LLM logger实例
llm_logger = setup_llm_logger()


def get_llm_logger(name: str = None) -> logging.Logger:
    """
    获取LLM logger实例

    Args:
        name: logger名称（可选）

    Returns:
        logging.Logger: LLM logger实例
    """
    if name:
        return logging.getLogger(f'magi.llm.{name}')
    return llm_logger


def truncate_text(text: str, max_length: int = 5000) -> str:
    """
    截断过长的文本

    设置环境变量 MAGI_FULL_LOG=1 可以禁用截断，在日志文件中保存完整内容

    Args:
        text: 原始文本
        max_length: 最大长度

    Returns:
        截断后的文本
    """
    # 检查是否启用完整日志
    if os.getenv("MAGI_FULL_LOG") == "1":
        return text

    if len(text) <= max_length:
        return text
    return text[:max_length] + f"... (truncated, total {len(text)} chars)"


def log_llm_request(
    logger: logging.Logger,
    request_id: str,
    model: str,
    system_prompt: str,
    messages: list,
    **kwargs
):
    """
    记录LLM请求

    Args:
        logger: logger实例
        request_id: 请求ID
        model: 模型名称
        system_prompt: 系统提示
        messages: 消息列表
        **kwargs: 其他参数
    """
    logger.debug("=" * 80)
    logger.debug(f"LLM_REQUEST [{request_id}] | Model: {model}")
    logger.debug("-" * 80)
    logger.debug(f"System Prompt:\n{truncate_text(system_prompt, 2000)}")
    logger.debug("-" * 80)
    logger.debug("Messages:")
    for i, msg in enumerate(messages):
        logger.debug(f"  [{i}] {msg.get('role')}: {truncate_text(msg.get('content', ''), 1000)}")
    logger.debug("=" * 80)


def log_llm_response(
    logger: logging.Logger,
    request_id: str,
    response: str,
    success: bool = True,
    error: Optional[str] = None,
    duration_ms: Optional[int] = None,
    **metadata
):
    """
    记录LLM响应

    Args:
        logger: logger实例
        request_id: 请求ID
        response: 响应内容
        success: 是否成功
        error: 错误信息
        duration_ms: 耗时（毫秒）
        **metadata: 其他元数据
    """
    status = "SUCCESS" if success else "FAILED"
    logger.debug("=" * 80)
    logger.debug(f"LLM_RESPONSE [{request_id}] | {status}")
    if duration_ms:
        logger.debug(f"Duration: {duration_ms}ms")
    if error:
        logger.debug(f"Error: {error}")
    logger.debug("-" * 80)
    if success and response:
        logger.debug(f"Response:\n{truncate_text(response, 3000)}")
    logger.debug("=" * 80)
