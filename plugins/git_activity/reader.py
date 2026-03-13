"""Git reflog reader."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from .types import GitActivity


# Reflog line pattern:
# <old_sha> <new_sha> <author> <timestamp> <tz>\t<action>: <message>
REFLOG_PATTERN = re.compile(
    r"^([a-f0-9]+)\s+"           # old_sha
    r"([a-f0-9]+)\s+"             # new_sha
    r"(.+?)\s+"                   # author (name <email>)
    r"(\d+)\s+"                   # timestamp (unix)
    r"([+-]\d{4})\t"              # timezone
    r"(.*)$"                      # message
)

# Activity type patterns
ACTIVITY_PATTERNS = {
    "commit": re.compile(r"^commit\b", re.IGNORECASE),
    "checkout": re.compile(r"^checkout\b", re.IGNORECASE),
    "merge": re.compile(r"^merge\b", re.IGNORECASE),
    "rebase": re.compile(r"^rebase\b", re.IGNORECASE),
    "reset": re.compile(r"^reset\b", re.IGNORECASE),
    "clone": re.compile(r"^clone\b", re.IGNORECASE),
    "pull": re.compile(r"^pull\b", re.IGNORECASE),
    "branch": re.compile(r"^branch\b", re.IGNORECASE),
    "amend": re.compile(r"^amend\b|^commit.*--amend", re.IGNORECASE),
    "cherry-pick": re.compile(r"^cherry[- ]?pick\b", re.IGNORECASE),
    "stash": re.compile(r"^stash\b", re.IGNORECASE),
}


class GitReflogReader:
    """Reads git reflog entries from a repository."""

    def __init__(self, repo_path: str):
        """Initialize the reader.

        Args:
            repo_path: Path to the git repository.
        """
        self.repo_path = Path(repo_path).expanduser().resolve()
        self._reflog_path: Optional[Path] = None

    @property
    def reflog_path(self) -> Path:
        """Get the path to the reflog file."""
        if self._reflog_path is None:
            self._reflog_path = self.repo_path / ".git" / "logs" / "HEAD"
        return self._reflog_path

    def is_available(self) -> bool:
        """Check if the repository and reflog are available.

        Returns:
            True if the reflog file exists and is readable.
        """
        return self.reflog_path.exists() and self.reflog_path.is_file()

    def read_activities(
        self,
        start_timestamp: Optional[float] = None,
        limit: int = 200,
    ) -> list[GitActivity]:
        """Read activities from the reflog.

        Args:
            start_timestamp: Only read activities after this timestamp. If None, read all.
            limit: Maximum number of activities to read.

        Returns:
            List of GitActivity objects.
        """
        if not self.is_available():
            return []

        activities = list(self._parse_reflog(start_timestamp, limit))
        return activities

    def _parse_reflog(
        self,
        start_timestamp: Optional[float],
        limit: int,
    ) -> Generator[GitActivity, None, None]:
        """Parse the reflog file and yield activities.

        Args:
            start_timestamp: Only yield activities after this timestamp.
            limit: Maximum number of activities to yield.

        Yields:
            GitActivity objects.
        """
        try:
            with open(self.reflog_path, "r", encoding="utf-8", errors="replace") as f:
                count = 0

                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue

                    activity = self._parse_line(line)
                    if activity is None:
                        continue

                    # Filter by timestamp if specified
                    if start_timestamp is not None:
                        if activity.timestamp.timestamp() < start_timestamp:
                            continue

                    yield activity

                    count += 1
                    if count >= limit:
                        break

        except Exception:
            pass

    def _parse_line(self, line: str) -> Optional[GitActivity]:
        """Parse a single reflog line.

        Args:
            line: The raw line from reflog.

        Returns:
            GitActivity or None if parsing fails.
        """
        match = REFLOG_PATTERN.match(line)
        if not match:
            return None

        old_sha = match.group(1)
        new_sha = match.group(2)
        author = match.group(3)
        timestamp_str = match.group(4)
        tz_str = match.group(5)
        message = match.group(6)

        try:
            # Parse timestamp
            timestamp = datetime.fromtimestamp(int(timestamp_str))

            # Determine activity type from message
            activity_type = self._determine_activity_type(message)

            return GitActivity(
                repo_path=str(self.repo_path),
                activity_type=activity_type,
                old_sha=old_sha,
                new_sha=new_sha,
                message=message,
                author=author,
                timestamp=timestamp,
                raw_line=line,
            )
        except (ValueError, TypeError):
            return None

    def _determine_activity_type(self, message: str) -> str:
        """Determine the activity type from the message.

        Args:
            message: The reflog message.

        Returns:
            Activity type string.
        """
        for activity_type, pattern in ACTIVITY_PATTERNS.items():
            if pattern.search(message):
                return activity_type

        # Default to "other" if no pattern matches
        return "other"

    def get_latest_timestamp(self) -> Optional[float]:
        """Get the timestamp of the most recent activity.

        Returns:
            Unix timestamp or None if not available.
        """
        if not self.is_available():
            return None

        try:
            activities = self.read_activities(limit=1)
            if activities:
                return activities[0].timestamp.timestamp()
        except Exception:
            return None


def is_git_repo(path: str) -> bool:
    """Check if a path is a valid git repository.

    Args:
        path: Path to check.

    Returns:
        True if it's a git repository.
    """
    repo_path = Path(path).expanduser().resolve()
    git_dir = repo_path / ".git"
    return git_dir.exists() and git_dir.is_dir()
