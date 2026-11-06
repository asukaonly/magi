"""Typed failures exposed by the memory portability boundary."""

from __future__ import annotations

import errno
import sqlite3


class MemoryPortabilityError(RuntimeError):
    """A safe, stable portability failure that never includes secret input."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = str(code)
        self.status_code = int(status_code)


class BackupPasswordRequiredError(MemoryPortabilityError):
    """Signal that an encrypted backup needs a password before inspection."""

    def __init__(self) -> None:
        super().__init__(
            "password_required",
            "This backup is encrypted and requires its password.",
        )


def is_no_space_error(exc: BaseException) -> bool:
    """Recognize filesystem or SQLite capacity failures through exception chains."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == errno.ENOSPC:
            return True
        if isinstance(current, sqlite3.Error) and getattr(
            current, "sqlite_errorcode", None
        ) == getattr(sqlite3, "SQLITE_FULL", 13):
            return True
        current = current.__cause__ or current.__context__
    return False


__all__ = ["BackupPasswordRequiredError", "MemoryPortabilityError", "is_no_space_error"]
