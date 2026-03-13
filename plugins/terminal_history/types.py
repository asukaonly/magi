"""Data types for Terminal History plugin."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TerminalCommand:
    """A single terminal command from history."""

    command: str                    # The executed command
    executed_at: datetime           # When the command was executed
    shell: str                      # zsh or bash
    history_line: int               # Line number in history file (for identity)
    raw_line: str                   # Original line from history file
