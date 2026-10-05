from __future__ import annotations

import logging
import pytest
import re
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock

from magi.utils import agent_logger as agent_logger_module
from magi.utils import llm_logger as llm_logger_module


def _reset_logger_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.parametrize("kind", ["agent", "llm"])
def test_special_loggers_emit_unified_records_to_their_configured_outputs(
    tmp_path, monkeypatch, kind
):
    from io import StringIO

    module = agent_logger_module if kind == "agent" else llm_logger_module
    name = module.AGENT_CHAIN_LOGGER_BASE if kind == "agent" else module.LLM_CALL_LOGGER_BASE
    setup = module.setup_agent_logger if kind == "agent" else module.setup_llm_logger
    logger = logging.getLogger(name)
    _reset_logger_handlers(logger)
    path = tmp_path / f"{kind}.log"
    stream = StringIO()
    monkeypatch.setattr(
        module, "_get_agent_log_file" if kind == "agent" else "_get_llm_log_file", lambda: str(path)
    )
    if kind == "llm":
        monkeypatch.setattr(llm_logger_module.sys, "stdout", stream)
    try:
        configured = setup()
        assert configured is logger
        assert setup() is configured
        handler = next(h for h in configured.handlers if isinstance(h, RotatingFileHandler))
        configured.info("special message")
        handler.flush()
        line = path.read_text().strip()
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \["
            + re.escape(name)
            + r"\] special message",
            line,
        )
        if kind == "llm":
            assert stream.getvalue().strip() == line
        handler.maxBytes = 1024
        handler.backupCount = 2
        for index in range(6):
            configured.info(f"marker-{index} " + "x" * 900)
        handler.flush()
        assert {p.name for p in tmp_path.iterdir()} == {
            f"{kind}.log",
            f"{kind}.log.1",
            f"{kind}.log.2",
        }
        for suffix, index in [("", 5), (".1", 4), (".2", 3)]:
            assert re.findall(r"marker-\d", (tmp_path / f"{kind}.log{suffix}").read_text()) == [
                f"marker-{index}"
            ]
    finally:
        _reset_logger_handlers(logger)


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


@pytest.mark.parametrize("use_boundary", [True, False])
def test_request_log_keeps_prompt_contents_and_labels_cache_segments(use_boundary) -> None:
    boundary = "<!--MAGI_CACHE_BOUNDARY-->"
    logger = MagicMock()
    system_prompt = (
        f"STABLE HEAD\n{boundary}\nPER-TURN TAIL with time"
        if use_boundary
        else "plain system prompt, no boundary"
    )

    llm_logger_module.log_llm_request(
        logger,
        request_id="req-1",
        model="claude-opus-4-8",
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": "hi"}],
        cache_boundary=boundary if use_boundary else None,
    )

    text = _debug_text(logger)

    if use_boundary:
        assert "cacheable head" in text and "per-turn tail" in text
        assert "STABLE HEAD" in text and "PER-TURN TAIL with time" in text
        assert boundary not in text
    else:
        assert "System Prompt:" in text
        assert system_prompt in text
        assert "cacheable head" not in text and "per-turn tail" not in text


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
