"""Tests for SafeStreamHandler: logging must survive a console encoding that
cannot represent some characters (e.g. emoji on a Windows gbk stdout)."""
from __future__ import annotations

import io
import logging
import pytest

from magi.utils.safe_logging import SafeStreamHandler


def _gbk_logger(name: str) -> tuple[logging.Logger, io.BytesIO]:
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="gbk", errors="strict", newline="")
    handler = SafeStreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, buf


@pytest.mark.parametrize(
    "message,expected",
    [("plain ascii line", "plain ascii line\n"), ("alpha 😀 omega", "alpha \\U0001f600 omega\n")],
)
def test_console_encoding_preserves_content_or_escapes_only_unrepresentable_characters(
    message, expected
):
    logger, buffer = _gbk_logger("test.safe_logging.encoding")
    try:
        logger.info(message)
        for handler in logger.handlers:
            handler.flush()
        assert buffer.getvalue().decode("gbk") == expected
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.stream.close()
            handler.close()
