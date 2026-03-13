"""Data types for Git Activity plugin."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class GitActivity:
    """A single git activity from reflog."""

    repo_path: str                    # Repository path
    activity_type: str                # commit/checkout/merge/rebase/reset/clone/pull
    old_sha: str                      # Previous commit SHA
    new_sha: str                      # New commit SHA
    message: str                      # Operation message
    author: str                        # Author name and email
    timestamp: datetime               # Operation timestamp
    raw_line: str                     # Original reflog line
