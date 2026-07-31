from __future__ import annotations

import logging
import re
from io import StringIO
from logging.handlers import RotatingFileHandler

from magi.core.logger import configure_logging, get_logger
from magi.utils.log_redaction import refresh_known_log_secrets


def test_configure_logging_formats_stdlib_logs_with_milliseconds(monkeypatch) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)

    configure_logging(level="INFO", json_logs=False)

    logging.getLogger("magi.test.stdlib").info("stdlib message")

    output = stream.getvalue().strip()
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.test\.stdlib\] stdlib message$",
        output,
    )


def test_configure_logging_includes_stdlib_extra_fields(monkeypatch) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)

    configure_logging(level="INFO", json_logs=False)

    logging.getLogger("magi.test.stdlib").info(
        "stdlib message",
        extra={"plugin_id": "calendar", "path": "/tmp/plugin"},
    )

    output = stream.getvalue().strip()
    assert "plugin_id='calendar'" in output
    assert "path='/tmp/plugin'" in output


def test_configure_logging_formats_structlog_logs_with_milliseconds(monkeypatch) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)

    configure_logging(level="INFO", json_logs=False)

    get_logger("magi.test.structlog").info("structlog message")

    output = stream.getvalue().strip()
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.test\.structlog\] structlog message$",
        output,
    )


def test_get_logger_auto_configures_unified_format(monkeypatch) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)
    monkeypatch.setattr("magi.core.logger._LOGGING_CONFIGURED", False)

    get_logger("magi.test.autoconfig").info("auto configured message")

    output = stream.getvalue().strip()
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.test\.autoconfig\] auto configured message$",
        output,
    )


def test_configure_logging_uses_rotating_file_handler_for_log_file(tmp_path) -> None:
    log_path = tmp_path / "magi.log"

    configure_logging(level="INFO", log_file=str(log_path), json_logs=False)

    root_logger = logging.getLogger()
    file_handlers = [
        handler
        for handler in root_logger.handlers
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(log_path)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 100 * 1024 * 1024
    assert file_handlers[0].backupCount == 10


def test_all_root_log_paths_redact_configured_and_structured_secrets(
    monkeypatch,
) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)
    refresh_known_log_secrets(
        {"network": {"password": "root-config-secret"}},
        environment={},
    )
    configure_logging(level="INFO", json_logs=False)

    logging.getLogger("magi.test.stdlib").error(
        "request failed with root-config-secret Authorization: Bearer header-secret"
    )
    get_logger("magi.test.structlog").error(
        "provider failed",
        api_key="structured-secret",
        input_tokens=42,
    )

    output = stream.getvalue()
    assert "root-config-secret" not in output
    assert "header-secret" not in output
    assert "structured-secret" not in output
    assert "input_tokens=42" in output
    assert output.count("[REDACTED]") >= 3
