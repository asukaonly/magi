"""Console logging that tolerates the platform console encoding.

On Windows the console stream is frequently gbk-encoded. Emitting a log record
that contains characters outside that encoding (emoji, some CJK, etc.) raises
UnicodeEncodeError inside the handler; the stdlib StreamHandler then routes it
to ``handleError``, flooding stderr with tracebacks for every such record.

``SafeStreamHandler`` writes the record normally and, only on an encoding
failure, retries with a lossy but safe rendering so logging never spams or
breaks the caller.
"""
from __future__ import annotations

import logging


class SafeStreamHandler(logging.StreamHandler):
    """StreamHandler whose emit survives characters the stream cannot encode."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe = msg.encode(encoding, errors="backslashreplace").decode(
                    encoding, errors="replace"
                )
                stream.write(safe + self.terminator)
            self.flush()
        except RecursionError:  # pragma: no cover - mirrors stdlib StreamHandler
            raise
        except Exception:  # noqa: BLE001 - matches stdlib StreamHandler behavior
            self.handleError(record)


__all__ = ["SafeStreamHandler"]
