from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock

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
    assert len(configured_logger.handlers) == 2

    file_handler = next(
        handler for handler in configured_logger.handlers if isinstance(handler, RotatingFileHandler)
    )
    stream_handler = next(
        handler
        for handler in configured_logger.handlers
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
    )

    record = configured_logger.makeRecord(
        configured_logger.name,
        logging.INFO,
        __file__,
        1,
        "llm test message",
        args=(),
        exc_info=None,
    )
    rendered = file_handler.formatter.format(record)
    stream_rendered = stream_handler.formatter.format(record)
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.llm\.calls\] llm test message$",
        rendered,
    )
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.llm\.calls\] llm test message$",
        stream_rendered,
    )


def test_log_llm_request_pretty_prints_tool_json_content() -> None:
    logger = MagicMock()

    llm_logger_module.log_llm_request(
        logger,
        request_id="req-1",
        model="test-model",
        system_prompt="sys",
        messages=[
            {
                "role": "tool",
                "content": (
                    '{"success": true, "data": {"memory_context": "用户喜欢下雨天\\n也喜欢阴天", '
                    '"meta": {"intent_source": "llm"}}}'
                ),
            }
        ],
    )

    rendered_messages = "\n".join(call.args[0] for call in logger.debug.call_args_list)
    assert "用户喜欢下雨天" in rendered_messages
    assert "\\u7528\\u6237" not in rendered_messages
    assert '"memory_context": "用户喜欢下雨天\\n也喜欢阴天"' not in rendered_messages


def _debug_text(mock_logger: MagicMock) -> str:
    return "\n".join(str(call.args[0]) for call in mock_logger.debug.call_args_list)


def test_log_llm_request_splits_system_prompt_at_cache_boundary() -> None:
    boundary = "<!--MAGI_CACHE_BOUNDARY-->"
    logger = MagicMock()
    system_prompt = f"STABLE HEAD\n{boundary}\nPER-TURN TAIL with time"

    llm_logger_module.log_llm_request(
        logger,
        request_id="req-1",
        model="claude-opus-4-8",
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": "hi"}],
        cache_boundary=boundary,
    )

    text = _debug_text(logger)
    # Two labeled sections; the boundary marker itself never appears in the log.
    assert "cacheable head" in text
    assert "per-turn tail" in text
    assert "STABLE HEAD" in text
    assert "PER-TURN TAIL with time" in text
    assert boundary not in text


def test_log_llm_request_no_boundary_logs_plain_system_prompt() -> None:
    logger = MagicMock()
    llm_logger_module.log_llm_request(
        logger,
        request_id="req-2",
        model="claude-opus-4-8",
        system_prompt="plain system prompt, no boundary",
        messages=[{"role": "user", "content": "hi"}],
    )

    text = _debug_text(logger)
    assert "System Prompt:" in text
    assert "cacheable head" not in text


def test_llm_log_setting_omits_content_but_keeps_diagnostics(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(
        llm_logger_module,
        "full_content_logging_enabled",
        lambda: False,
    )

    llm_logger_module.log_llm_request(
        logger,
        request_id="req-disabled",
        model="test-model",
        system_prompt="SYSTEM-CONTENT-CANARY",
        messages=[{"role": "user", "content": "USER-CONTENT-CANARY"}],
        temperature=0.5,
    )
    llm_logger_module.log_llm_response(
        logger,
        request_id="req-disabled",
        response="RESPONSE-CONTENT-CANARY",
        metadata={"assistant_message": "METADATA-CONTENT-CANARY"},
    )

    text = _debug_text(logger)
    assert "SYSTEM-CONTENT-CANARY" not in text
    assert "USER-CONTENT-CANARY" not in text
    assert "RESPONSE-CONTENT-CANARY" not in text
    assert "METADATA-CONTENT-CANARY" not in text
    assert "System prompt chars:" in text
    assert "Response chars:" in text
    assert "Parameter names:" in text


def test_llm_logs_keep_text_but_redact_known_secrets(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(
        llm_logger_module,
        "full_content_logging_enabled",
        lambda: True,
    )

    llm_logger_module.log_llm_request(
        logger,
        request_id="req-redacted",
        model="test-model",
        system_prompt="api_key=system-secret",
        messages=[
            {
                "role": "user",
                "content": "Keep this useful prompt. Authorization: Bearer prompt-secret",
            }
        ],
    )

    text = _debug_text(logger)
    assert "Keep this useful prompt." in text
    assert "system-secret" not in text
    assert "prompt-secret" not in text
    assert "[REDACTED]" in text


def test_llm_logs_omit_inline_image_bodies(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(
        llm_logger_module,
        "full_content_logging_enabled",
        lambda: True,
    )
    image_data = "A" * 128

    llm_logger_module.log_llm_request(
        logger,
        request_id="req-image",
        model="vision-model",
        system_prompt="system",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this"},
                    {
                        "type": "image",
                        "mime_type": "image/png",
                        "data": image_data,
                    },
                ],
            }
        ],
    )

    text = _debug_text(logger)
    assert "describe this" in text
    assert image_data not in text
    assert "[binary content omitted]" in text
