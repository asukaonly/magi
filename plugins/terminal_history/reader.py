"""Terminal history file reader."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from .exceptions import ShellNotSupportedError, HistoryFileNotFoundError, HistoryFileReadError
from .types import TerminalCommand


# Default history file locations
DEFAULT_ZSH_HISTORY = "~/.zsh_history"
DEFAULT_BASH_HISTORY = "~/.bash_history"

# Zsh extended history format: `: timestamp:duration;command`
# Regex to match zsh extended history format
ZSH_EXTENDED_PATTERN = re.compile(r"^: (\d+):\d+;(.*)$")

# Supported shells and their history file paths
SHELL_CONFIGS = {
    "zsh": {
        "history_file": DEFAULT_ZSH_HISTORY,
        "has_timestamps": True,
    },
    "bash": {
        "history_file": DEFAULT_BASH_HISTORY,
        "has_timestamps": False,  # bash doesn't have timestamps by default
    },
    "/bin/zsh": {
        "history_file": DEFAULT_ZSH_HISTORY,
        "has_timestamps": True,
    },
    "/bin/bash": {
        "history_file": DEFAULT_BASH_HISTORY,
        "has_timestamps": False,
    },
}


class TerminalHistoryReader:
    """Reads terminal command history from shell history files."""

    def __init__(self, shell: Optional[str] = None, history_file: Optional[str] = None):
        """Initialize the reader.

        Args:
            shell: Shell type (zsh/bash). If None, auto-detect from $SHELL.
            history_file: Path to history file. If None, use default for shell.
        """
        self._shell = shell
        self._history_file = history_file
        self._cached_shell: Optional[str] = None
        self._cached_history_file: Optional[Path] = None

    @property
    def shell(self) -> str:
        """Get the shell type, Auto-detect if not set."""
        if self._cached_shell is None:
            self._cached_shell = self._detect_shell()
        return self._cached_shell

    @property
    def history_file(self) -> Path:
        """Get the history file path."""
        if self._cached_history_file is None:
            self._cached_history_file = self._resolve_history_file()
        return self._cached_history_file

    @property
    def has_timestamps(self) -> bool:
        """Check if the shell supports timestamps in history."""
        shell_config = SHELL_CONFIGS.get(self.shell, {})
        return shell_config.get("has_timestamps", False)

    def _detect_shell(self) -> str:
        """Detect the shell from $SHELL environment variable."""
        if self._shell:
            shell = self._shell
        else:
            shell = os.environ.get("SHELL", "bash")

        # Normalize shell name
        shell_name = Path(shell).name if "/" in shell else shell

        if shell_name not in ["zsh", "bash"]:
            raise ShellNotSupportedError(shell_name)

        return shell_name

    def _resolve_history_file(self) -> Path:
        """Resolve the history file path."""
        if self._history_file:
            path = Path(self._history_file).expanduser()
        else:
            shell_config = SHELL_CONFIGS.get(self.shell, {})
            default_path = shell_config.get("history_file", DEFAULT_ZSH_HISTORY)
            path = Path(default_path).expanduser()

        if not path.exists():
            raise HistoryFileNotFoundError(str(path))

        return path

    def is_available(self) -> bool:
        """Check if history reading is available.

        Returns:
            True if the shell is supported and history file exists.
        """
        # Not available on non-darwin platforms
        if sys.platform != "darwin":
            return False

        try:
            shell = self._detect_shell()
            # Check if history file exists
            if self._history_file:
                path = Path(self._history_file).expanduser()
            else:
                shell_config = SHELL_CONFIGS.get(shell, {})
                default_path = shell_config.get("history_file", DEFAULT_ZSH_HISTORY)
                path = Path(default_path).expanduser()
            return path.exists()
        except Exception:
            return False

    def read_commands(
        self,
        start_timestamp: Optional[float] = None,
        limit: int = 200,
    ) -> list[TerminalCommand]:
        """Read commands from the history file.

        Args:
            start_timestamp: Only read commands after this timestamp. If None, read all.
            limit: Maximum number of commands to read.

        Returns:
            List of TerminalCommand objects.
        """
        if not self.is_available():
            return []

        try:
            commands = list(self._parse_history_file(start_timestamp, limit))
            return commands
        except Exception as e:
            raise HistoryFileReadError(str(self.history_file), str(e))

    def _parse_history_file(
        self,
        start_timestamp: Optional[float],
        limit: int,
    ) -> Generator[TerminalCommand, None, None]:
        """Parse the history file and yield commands.

        Args:
            start_timestamp: Only yield commands after this timestamp.
            limit: Maximum number of commands to yield.

        Yields:
            TerminalCommand objects.
        """
        history_path = self.history_file
        shell = self.shell

        with open(history_path, "r", encoding="utf-8", errors="replace") as f:
            line_number = 0
            count = 0

            for line in f:
                line_number += 1
                line = line.rstrip("\n")

                if not line:
                    continue

                command, timestamp = self._parse_line(line, shell)

                if not command:
                    continue

                # Filter by timestamp if specified
                if start_timestamp is not None:
                    if timestamp is None or timestamp < start_timestamp:
                        continue

                yield TerminalCommand(
                    command=command,
                    executed_at=datetime.fromtimestamp(timestamp) if timestamp else datetime.now(),
                    shell=shell,
                    history_line=line_number,
                    raw_line=line,
                )

                count += 1
                if count >= limit:
                    break

    def _parse_line(self, line: str, shell: str) -> tuple[Optional[str], Optional[float]]:
        """Parse a single history line.

        Args:
            line: The raw line from history file.
            shell: The shell type.

        Returns:
            Tuple of (command, timestamp). timestamp may be None.
        """
        if shell == "zsh":
            return self._parse_zsh_line(line)
        else:
            return self._parse_bash_line(line)

    def _parse_zsh_line(self, line: str) -> tuple[Optional[str], Optional[float]]:
        """Parse a zsh history line.

        Extended format: `: timestamp:duration;command`
        Basic format: `command`

        Args:
            line: The raw line from history file.

        Returns:
            Tuple of (command, timestamp).
        """
        match = ZSH_EXTENDED_PATTERN.match(line)
        if match:
            timestamp = int(match.group(1))
            command = match.group(2).strip()
            return command, float(timestamp)
        else:
            # Basic format - no timestamp
            return line.strip() if line.strip() else None, None

    def _parse_bash_line(self, line: str) -> tuple[Optional[str], Optional[float]]:
        """Parse a bash history line.

        Bash history typically has no timestamps.
        Format: just the command

        Args:
            line: The raw line from history file.

        Returns:
            Tuple of (command, None) - bash doesn't have timestamps.
        """
        # Bash history is just the raw command
        return line.strip() if line.strip() else None, None

    def get_latest_timestamp(self) -> Optional[float]:
        """Get the timestamp of the most recent command in history.

        Returns:
            Unix timestamp or None if not available.
        """
        if not self.is_available():
            return None

        try:
            commands = self.read_commands(limit=1)
            if commands:
                return commands[0].executed_at.timestamp()
        except Exception:
            return None
