"""Sensitive message filter for Git Activity plugin.

Reuses logic from terminal_history for consistency.
"""
from __future__ import annotations

import re
from typing import Optional


# Import from terminal_history if available, otherwise define locally
try:
    from terminal_history.filters import (
        SensitiveCommandFilter,
        BUILTIN_SENSITIVE_KEYWORDS,
        SENSITIVE_VALUE_PATTERNS,
    )
except ImportError:
    # Define locally if terminal_history is not available
    BUILTIN_SENSITIVE_KEYWORDS = [
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "access_key", "private_key", "credential", "auth", "db_pass",
        "mysql_pass", "aws_secret", "ssh_key", "aws_access_key",
    ]

    SENSITIVE_VALUE_PATTERNS = [
        # Environment variable assignments with sensitive names
        re.compile(r"(\w*(?:password|secret|token|key|credential)\w*)\s*=\s*\S+", re.IGNORECASE),
        # URL with credentials
        re.compile(r"(https?://)[^:]+:[^@]+@"),
        # Base64-like strings that look like secrets
        re.compile(r"(?:key|token|secret)[=:\s]+[A-Za-z0-9+/]{20,}", re.IGNORECASE),
    ]


class SensitiveMessageFilter:
    """Filter for sensitive git commit messages."""

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

    def should_block(self, message: str) -> bool:
        """Check if a message should be blocked entirely.

        Args:
            message: The commit message to check.

        Returns:
            True if the message should be blocked.
        """
        if self.mode != "block":
            return False

        return self._contains_sensitive_keyword(message)

    def redact(self, message: str) -> str:
        """Redact sensitive parts of a message.

        Args:
            message: The commit message to redact.

        Returns:
            The message with sensitive values replaced by ***.
        """
        if self.mode != "redact":
            return message

        # First check if it contains sensitive content
        if not self._contains_sensitive_keyword(message):
            return message

        result = message

        # Redact environment variable-like patterns
        for pattern in SENSITIVE_VALUE_PATTERNS:
            result = pattern.sub(
                lambda m: self._redact_match(m, result),
                result
            )

        # Simple regex for =value patterns with sensitive keys
        sensitive_assignment = re.compile(
            r"(\w*(?:" + "|".join(re.escape(kw) for kw in self.keywords) + r")\w*)\s*=\s*(\S+)",
            re.IGNORECASE
        )
        result = sensitive_assignment.sub(r"\1=***", result)

        return result

    def _contains_sensitive_keyword(self, message: str) -> bool:
        """Check if message contains any sensitive keywords.

        Args:
            message: The commit message to check.

        Returns:
            True if a sensitive keyword is found.
        """
        message_lower = message.lower()
        return any(kw in message_lower for kw in self.keywords)

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

    def process(self, message: str) -> Optional[str]:
        """Process a message: block or redact based on mode.

        Args:
            message: The commit message to process.

        Returns:
            None if blocked, otherwise the (possibly redacted) message.
        """
        if self.should_block(message):
            return None
        return self.redact(message)
