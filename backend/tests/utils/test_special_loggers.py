from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from magi.utils import agent_logger as agent_logger_module
from magi.utils import llm_logger as llm_logger_module


def _reset_logger_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_agent_logger_uses_rotating_file_handler_with_unified_format(tmp_path, monkeypatch) -> None:
    logger = logging.getLogger(agent_logger_module.AGENT_CHAIN_LOGGER_BASE)
    _reset_logger_handlers(logger)
    monkeypatch.setattr(
        "magi.utils.agent_logger._get_agent_log_file",
        lambda: str(tmp_path / "agent_chain.log"),
    )

    configured_logger = agent_logger_module.setup_agent_logger()

    assert configured_logger.name == agent_logger_module.AGENT_CHAIN_LOGGER_BASE
    assert len(configured_logger.handlers) == 1
    assert isinstance(configured_logger.handlers[0], RotatingFileHandler)

    record = configured_logger.makeRecord(
        configured_logger.name,
        logging.INFO,
        __file__,
        1,
        "agent test message",
        args=(),
        exc_info=None,
    )
    rendered = configured_logger.handlers[0].formatter.format(record)
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.agent\.chain\] agent test message$",
        rendered,
    )


def test_llm_logger_uses_rotating_file_handler_with_unified_format(tmp_path, monkeypatch) -> None:
    logger = logging.getLogger(llm_logger_module.LLM_CALL_LOGGER_BASE)
    _reset_logger_handlers(logger)
    monkeypatch.setattr(
        "magi.utils.llm_logger._get_llm_log_file",
        lambda: str(tmp_path / "llm_calls.log"),
    )

    configured_logger = llm_logger_module.setup_llm_logger()

    assert configured_logger.name == llm_logger_module.LLM_CALL_LOGGER_BASE
    assert len(configured_logger.handlers) == 1
    assert isinstance(configured_logger.handlers[0], RotatingFileHandler)

    record = configured_logger.makeRecord(
        configured_logger.name,
        logging.INFO,
        __file__,
        1,
        "llm test message",
        args=(),
        exc_info=None,
    )
    rendered = configured_logger.handlers[0].formatter.format(record)
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.llm\.calls\] llm test message$",
        rendered,
    )

