"""Sensitive command filtering and redaction for Terminal History plugin."""
from __future__ import annotations

import re
from typing import Optional


# Built-in sensitive keywords that should be filtered/redacted
BUILTIN_SENSITIVE_KEYWORDS = [
    # Password related
    "password",
    "passwd",
    "pwd",
    # Secrets and tokens
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "priv_key",
    # Credentials
    "credential",
    "auth",
    # Database passwords
    "db_pass",
    "mysql_pass",
    "postgres_pass",
    "mongo_pass",
    "redis_pass",
    # Cloud provider secrets
    "aws_secret",
    "aws_access_key",
    "azure_key",
    "gcp_key",
    # Other common patterns
    "private_token",
    "access_token",
    "refresh_token",
    "bearer",
    "jwt",
]

# Patterns for detecting sensitive values
SENSITIVE_VALUE_PATTERNS = [
    # Environment variable assignments with sensitive names
    re.compile(r"(\w*(?:password|secret|token|key|credential)\w*)\s*=\s*\S+", re.IGNORECASE),
    # URL with credentials
    re.compile(r"(https?://)[^:]+:[^@]+@"),
    # Base64-like strings that look like secrets (longer than 20 chars)
    re.compile(r"(?:key|token|secret)[=:\s]+[A-Za-z0-9+/]{20,}", re.IGNORECASE),
]


class SensitiveCommandFilter:
    """Filters and redacts sensitive commands."""

    def __init__(
        self,
        mode: str = "redact",  # "block" or "redact"
        additional_keywords: Optional[list[str]] = None,
    ):
        """Initialize the filter.

        Args:
            mode: "block" to skip sensitive commands, "redact" to mask sensitive parts.
            additional_keywords: Extra keywords to treat as sensitive.
        """
        self.mode = mode
        self.keywords = set(BUILTIN_SENSITIVE_KEYWORDS)
        if additional_keywords:
            self.keywords.update(kw.lower() for kw in additional_keywords)

    def should_block(self, command: str) -> bool:
        """Check if a command should be blocked entirely.

        Args:
            command: The command to check.

        Returns:
            True if the command should be blocked.
        """
        if self.mode != "block":
            return False

        return self._contains_sensitive_keyword(command)

    def redact(self, command: str) -> str:
        """Redact sensitive parts of a command.

        Args:
            command: The command to redact.

        Returns:
            The command with sensitive values replaced by ***.
        """
        if self.mode != "redact":
            return command

        # First check if it contains sensitive content
        if not self._contains_sensitive_keyword(command):
            return command

        result = command

        # Redact environment variable assignments
        for pattern in SENSITIVE_VALUE_PATTERNS:
            result = pattern.sub(
                lambda m: self._redact_match(m, result),
                result
            )

        # Simple regex for =value patterns with sensitive keys
        # Matches: KEY=sensitive_value
        sensitive_assignment = re.compile(
            r"(\w*(?:" + "|".join(re.escape(kw) for kw in self.keywords) + r")\w*)\s*=\s*(\S+)",
            re.IGNORECASE
        )
        result = sensitive_assignment.sub(r"\1=***", result)

        return result

    def _contains_sensitive_keyword(self, command: str) -> bool:
        """Check if command contains any sensitive keywords.

        Args:
            command: The command to check.

        Returns:
            True if a sensitive keyword is found.
        """
        command_lower = command.lower()
        return any(kw in command_lower for kw in self.keywords)

    def _redact_match(self, match: re.Match, original: str) -> str:
        """Redact a regex match.

        Args:
            match: The regex match object.
            original: The original string.

        Returns:
            The redacted version.
        """
        matched = match.group(0)
        # Keep the key, redact the value
        if "=" in matched:
            key_part = matched.split("=")[0] + "="
            return key_part + "***"
        return "***"

    def process(self, command: str) -> Optional[str]:
        """Process a command: block or redact based on mode.

        Args:
            command: The command to process.

        Returns:
            None if blocked, otherwise the (possibly redacted) command.
        """
        if self.should_block(command):
            return None
        return self.redact(command)
