"""Tests for SafeStreamHandler: logging must survive a console encoding that
cannot represent some characters (e.g. emoji on a Windows gbk stdout)."""
from __future__ import annotations

import io
import logging

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


def test_emit_does_not_raise_on_unencodable_char() -> None:
    logger, buf = _gbk_logger("test.safe_logging.emoji")
    # U+1F600 is not representable in gbk; a plain StreamHandler would route this
    # to handleError and write nothing to the stream.
    logger.info("alpha \U0001F600 omega")
    for h in logger.handlers:
        h.flush()
    out = buf.getvalue().decode("gbk", errors="replace")
    assert "alpha" in out and "omega" in out


def test_encodable_text_passes_through_unchanged() -> None:
    logger, buf = _gbk_logger("test.safe_logging.plain")
    logger.info("plain ascii line")
    for h in logger.handlers:
        h.flush()
    out = buf.getvalue().decode("gbk", errors="replace")
    assert "plain ascii line" in out
