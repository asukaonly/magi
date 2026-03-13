"""Custom exceptions for Terminal History plugin."""
from __future__ import annotations


class TerminalHistoryError(Exception):
    """Base exception for Terminal History-related errors."""
    pass


class ShellNotSupportedError(TerminalHistoryError):
    """Raised when the shell is not supported."""

    def __init__(self, shell: str):
        self.shell = shell
        super().__init__(f"Shell '{shell}' is not supported. Only zsh and bash are supported.")


class HistoryFileNotFoundError(TerminalHistoryError):
    """Raised when the history file cannot be found."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"History file not found: {path}")


class HistoryFileReadError(TerminalHistoryError):
    """Raised when reading the history file fails."""

    def __init__(self, path: str, reason: str = ""):
        self.path = path
        message = f"Failed to read history file: {path}"
        if reason:
            message = f"{message} - {reason}"
        super().__init__(message)
