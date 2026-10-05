from __future__ import annotations

import logging
import pytest
import re
from io import StringIO
from logging.handlers import RotatingFileHandler

from magi.core.logger import configure_logging, get_logger
from magi.utils.log_redaction import refresh_known_log_secrets


@pytest.mark.parametrize(
    "get_test_logger", [logging.getLogger, get_logger], ids=["stdlib", "structlog"]
)
def test_logging_apis_share_timestamped_format(monkeypatch, get_test_logger) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)

    configure_logging(level="INFO", json_logs=False)

    get_test_logger("magi.test.stdlib").info("stdlib message")

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


def test_file_logging_rotates_and_bounds_retained_history(tmp_path, monkeypatch):
    log_path = tmp_path / "magi.log"
    monkeypatch.setattr("magi.core.logger.DEFAULT_LOG_FILE_MAX_BYTES", 1024)
    monkeypatch.setattr("magi.core.logger.DEFAULT_LOG_FILE_BACKUP_COUNT", 2)
    monkeypatch.setattr("magi.core.logger.sys.stdout", StringIO())
    configure_logging(level="INFO", log_file=str(log_path), json_logs=False)
    root = logging.getLogger()
    handlers = [
        handler
        for handler in root.handlers
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(log_path)
    ]
    assert len(handlers) == 1
    try:
        for index in range(8):
            logging.getLogger("magi.test.rotation").info(f"marker-{index} " + "x" * 900)
        handlers[0].flush()
        assert {path.name for path in tmp_path.iterdir()} == {
            "magi.log",
            "magi.log.1",
            "magi.log.2",
        }
        for filename, index in [("magi.log", 7), ("magi.log.1", 6), ("magi.log.2", 5)]:
            path = tmp_path / filename
            contents = path.read_text()
            assert re.findall(r"marker-\d", contents) == [f"marker-{index}"]
            assert path.stat().st_size <= 1024
    finally:
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()


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
