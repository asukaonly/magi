from __future__ import annotations

import logging
import re
from io import StringIO

from magi.core.logger import configure_logging, get_logger


def test_configure_logging_formats_stdlib_logs_with_milliseconds(monkeypatch) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)

    configure_logging(level="INFO", json_logs=False)

    logging.getLogger("magi.test.stdlib").info("stdlib message")

    output = stream.getvalue().strip()
    assert re.search(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.test\.stdlib\] stdlib message$", output)


def test_configure_logging_formats_structlog_logs_with_milliseconds(monkeypatch) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)

    configure_logging(level="INFO", json_logs=False)

    get_logger("magi.test.structlog").info("structlog message")

    output = stream.getvalue().strip()
    assert re.search(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.test\.structlog\] structlog message$", output)


def test_get_logger_auto_configures_unified_format(monkeypatch) -> None:
    stream = StringIO()
    monkeypatch.setattr("magi.core.logger.sys.stdout", stream)
    monkeypatch.setattr("magi.core.logger._LOGGING_CONFIGURED", False)

    get_logger("magi.test.autoconfig").info("auto configured message")

    output = stream.getvalue().strip()
    assert re.search(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[magi\.test\.autoconfig\] auto configured message$", output)
