"""
LLM调用LogConfiguration

专门recordLLM调用的promptandOutputResult
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


def _get_llm_log_file():
    """getLLMLogfilepath（使用run时directory）"""
    from ..utils.runtime import get_runtime_paths
    runtime_paths = get_runtime_paths()
    return str(runtime_paths.logs_dir / 'llm_calls.log')


class LLMFormatter(logging.Formatter):
    """LLMLogformat化器 - structure化Logformat"""

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_llm_logger():
    """
    ConfigurationLLM专用logger

    Returns:
        logging.Logger: LLM专用loggerInstance
    """
    # createlogger
    llm_logger = logging.getLogger('magi.llm')
    llm_logger.setlevel(logging.debug)

    # 防止重复addhandler
    if llm_logger.handlers:
        return llm_logger

    # getLogfilepath
    llm_log_file = _get_llm_log_file()
    # 确保directoryexists
    os.makedirs(os.path.dirname(llm_log_file), exist_ok=True)

    # filehandler - 自动轮转
    file_handler = RotatingFileHandler(
        llm_log_file,
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setlevel(logging.debug)
    file_handler.setFormatter(LLMFormatter())

    # addhandler
    llm_logger.addHandler(file_handler)

    return llm_logger


# globalLLM loggerInstance
llm_logger = setup_llm_logger()


def get_llm_logger(name: str = None) -> logging.Logger:
    """
    getLLM loggerInstance

    Args:
        name: loggerName（optional）

    Returns:
        logging.Logger: LLM loggerInstance
    """
    if name:
        return logging.getLogger(f'magi.llm.{name}')
    return llm_logger


def truncate_text(text: str, max_length: int = 5000) -> str:
    """
    截断过长的文本

    Setting环境Variable MAGI_full_LOG=1 可以Disable截断，在Logfile中save完整Content

    Args:
        text: 原始文本
        max_length: maximumlength

    Returns:
        截断后的文本
    """
    # checkis nottttEnable完整Log
    if os.getenv("MAGI_full_LOG") == "1":
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
    recordLLMrequest

    Args:
        logger: loggerInstance
        request_id: requestid
        model: modelName
        system_prompt: 系统prompt
        messages: messagelist
        **kwargs: otherParameter
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
    recordLLMresponse

    Args:
        logger: loggerInstance
        request_id: requestid
        response: Response content
        success: is nottttsuccess
        error: errorinfo
        duration_ms: 耗时（毫seconds）
        **metadata: othermetadata
    """
    status = "SUCCESS" if success else "failED"
    logger.debug("=" * 80)
    logger.debug(f"LLM_RESPONSE [{request_id}] | {status}")
    if duration_ms:
        logger.debug(f"Duration: {duration_ms}ms")
    if error:
        logger.debug(f"error: {error}")
    logger.debug("-" * 80)
    if success and response:
        logger.debug(f"Response:\n{truncate_text(response, 3000)}")
    logger.debug("=" * 80)
