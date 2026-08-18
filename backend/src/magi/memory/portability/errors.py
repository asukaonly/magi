"""Typed failures exposed by the memory portability boundary."""

from __future__ import annotations


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


__all__ = ["BackupPasswordRequiredError", "MemoryPortabilityError"]
