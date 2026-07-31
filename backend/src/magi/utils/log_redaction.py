"""Shared redaction for every user-visible or persisted log sink.

The redactor deliberately combines three protections:

1. Structured values are inspected by field name.
2. Secrets loaded from Magi configuration are replaced by exact value.
3. High-confidence textual forms such as authorization headers, URL query
   parameters, private keys, and common provider token formats are masked.

Callers should still avoid logging unnecessary sensitive content. This module
is the final safety boundary, not permission to add arbitrary payload dumps.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import logging
import os
import re
import sys
from threading import RLock
from typing import Any, Iterable, Mapping, TextIO
from urllib.parse import quote, quote_plus


MASKED_LOG_VALUE = "[REDACTED]"
OMITTED_BINARY_VALUE = "[binary content omitted]"

_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_FIELD_SEPARATOR = re.compile(r"[^a-z0-9]+")

_NON_SECRET_TOKEN_FIELDS = frozenset(
    {
        "cached_tokens",
        "completion_tokens",
        "input_tokens",
        "max_output_tokens",
        "max_tokens",
        "output_tokens",
        "prompt_tokens",
        "reasoning_tokens",
        "token_budget",
        "token_count",
        "token_counts",
        "token_limit",
        "token_usage",
        "total_tokens",
    }
)

_EXACT_SENSITIVE_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "proxy_authorization",
        "pwd",
        "secret",
        "set_cookie",
        "sig",
        "signature",
        "signing_key",
        "token",
    }
)

_NON_SECRET_ENVIRONMENT_FIELDS = frozenset({"pwd"})

_TEXTUAL_SECRET_KEY = (
    r"(?:"
    r"(?:[a-z0-9]+[_-])*api[_-]?key"
    r"|x[_-][a-z0-9_-]*api[_-]?key"
    r"|access[_-]?token"
    r"|auth"
    r"|authorization"
    r"|auth[_-]?token"
    r"|bearer"
    r"|bearer[_-]?token"
    r"|bot[_-]?token"
    r"|client[_-]?secret"
    r"|cookie"
    r"|(?:[a-z0-9]+[_-])*credential(?:s)?"
    r"|password"
    r"|passwd"
    r"|private[_-]?key"
    r"|proxy[_-]?authorization"
    r"|pwd"
    r"|proxy[_-]?authorization"
    r"|refresh[_-]?token"
    r"|secret"
    r"|session[_-]?token"
    r"|set[_-]?cookie"
    r"|(?:[a-z0-9]+[_-])*signature"
    r"|sig"
    r"|signing[_-]?key"
    r"|token"
    r")"
)

_AUTH_HEADER_RE = re.compile(
    r"(?im)(?P<prefix>\b(?:authorization|proxy-authorization)\s*:\s*)[^\r\n]+"
)
_COOKIE_HEADER_RE = re.compile(
    r"(?im)(?P<prefix>\b(?:cookie|set-cookie)\s*:\s*)[^\r\n]+"
)
_BEARER_RE = re.compile(
    r"(?i)\b(?P<scheme>bearer|basic)\s+[a-z0-9._~+/=-]{3,}"
)
_QUOTED_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?P<prefix>(?<![a-z0-9_-])[\"']?{_TEXTUAL_SECRET_KEY}[\"']?"
    rf"\s*[:=]\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)"
)
_UNQUOTED_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?P<prefix>(?<![a-z0-9_-]){_TEXTUAL_SECRET_KEY}\s*[:=]\s*)"
    r"(?P<value>[^\s,;&#}\])]+)"
)
_URL_USERINFO_RE = re.compile(
    r"(?i)(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/@:\s]+):(?P<password>[^/@\s]+)@"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    flags=re.DOTALL,
)
_DATA_URL_RE = re.compile(
    r"data:(?P<mime>[a-z0-9.+-]+/[a-z0-9.+-]+);base64,"
    r"(?P<data>[a-z0-9+/=_-]{32,})",
    flags=re.IGNORECASE,
)
_HIGH_CONFIDENCE_TOKEN_RES = (
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{16,}\b", flags=re.IGNORECASE),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    ),
)

_KNOWN_SECRET_LOCK = RLock()
_KNOWN_SECRET_VALUES: tuple[str, ...] = ()


def normalize_log_field_name(field_name: str) -> str:
    """Normalize snake, kebab, dotted, and camel-case field names."""
    with_boundaries = _CAMEL_CASE_BOUNDARY.sub("_", str(field_name))
    return _FIELD_SEPARATOR.sub("_", with_boundaries.lower()).strip("_")


def is_sensitive_log_field(field_name: str) -> bool:
    """Return whether a structured field contains a secret value."""
    normalized = normalize_log_field_name(field_name)
    if not normalized:
        return False
    if normalized in _NON_SECRET_TOKEN_FIELDS:
        return False
    if normalized in _EXACT_SENSITIVE_FIELDS:
        return True
    if normalized.endswith(
        (
            "_api_key",
            "_auth_token",
            "_bot_token",
            "_client_secret",
            "_credential",
            "_credentials",
            "_password",
            "_private_key",
            "_refresh_token",
            "_secret",
            "_session_token",
            "_signature",
            "_signing_key",
        )
    ):
        return True
    if normalized.endswith("_token") and not normalized.endswith(
        ("_count_token", "_limit_token")
    ):
        return True
    if "secret" in normalized.split("_"):
        return True
    return False


def _collect_sensitive_strings(
    value: Any,
    *,
    sensitive_parent: bool = False,
    collected: set[str],
    seen: set[int],
) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if sensitive_parent and value:
            collected.add(value)
        return
    if isinstance(value, bytes):
        if sensitive_parent and value:
            collected.add(value.decode("utf-8", errors="ignore"))
        return

    value_id = id(value)
    if value_id in seen:
        return
    seen.add(value_id)

    if isinstance(value, Mapping):
        for key, item in value.items():
            _collect_sensitive_strings(
                item,
                sensitive_parent=(
                    sensitive_parent or is_sensitive_log_field(str(key))
                ),
                collected=collected,
                seen=seen,
            )
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_sensitive_strings(
                item,
                sensitive_parent=sensitive_parent,
                collected=collected,
                seen=seen,
            )
        return
    if hasattr(value, "model_dump"):
        try:
            _collect_sensitive_strings(
                value.model_dump(mode="python"),
                sensitive_parent=sensitive_parent,
                collected=collected,
                seen=seen,
            )
        except Exception:
            return
        return
    if is_dataclass(value) and not isinstance(value, type):
        _collect_sensitive_strings(
            asdict(value),
            sensitive_parent=sensitive_parent,
            collected=collected,
            seen=seen,
        )


def _environment_sensitive_values(environment: Mapping[str, str]) -> set[str]:
    return {
        value
        for key, value in environment.items()
        if (
            value
            and normalize_log_field_name(key) not in _NON_SECRET_ENVIRONMENT_FIELDS
            and is_sensitive_log_field(key)
        )
    }


def _secret_variants(secret: str) -> set[str]:
    variants = {secret}
    encoded = quote(secret, safe="")
    encoded_plus = quote_plus(secret, safe="")
    if encoded:
        variants.add(encoded)
    if encoded_plus:
        variants.add(encoded_plus)
    return variants


def register_log_secret_values(values: Iterable[str]) -> None:
    """Register explicit secret values that do not have meaningful field names."""
    variants: set[str] = set()
    for value in values:
        secret = str(value or "")
        if secret and not re.fullmatch(r"(?:\*{3,}|•{3,})", secret):
            variants.update(_secret_variants(secret))

    global _KNOWN_SECRET_VALUES
    with _KNOWN_SECRET_LOCK:
        variants.update(_KNOWN_SECRET_VALUES)
        _KNOWN_SECRET_VALUES = tuple(
            sorted(
                (
                    value
                    for value in variants
                    if value and value not in {MASKED_LOG_VALUE, OMITTED_BINARY_VALUE}
                ),
                key=len,
                reverse=True,
            )
        )


def refresh_known_log_secrets(
    config_value: Any,
    *,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Add current secrets to the process-wide exact-secret snapshot.

    Values intentionally remain registered until process exit. A provider may
    emit a delayed error after a credential has been rotated, and that error
    must still redact the previous value.
    """
    collected: set[str] = set()
    _collect_sensitive_strings(
        config_value,
        sensitive_parent=False,
        collected=collected,
        seen=set(),
    )
    collected.update(
        _environment_sensitive_values(os.environ if environment is None else environment)
    )

    register_log_secret_values(collected)


def _redact_known_secret_values(text: str) -> str:
    with _KNOWN_SECRET_LOCK:
        secrets = _KNOWN_SECRET_VALUES
    redacted = text
    for secret in secrets:
        if len(secret) >= 6:
            redacted = redacted.replace(secret, MASKED_LOG_VALUE)
            continue
        redacted = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(secret)}(?![A-Za-z0-9])",
            MASKED_LOG_VALUE,
            redacted,
        )
    return redacted


def redact_log_text(text: str) -> str:
    """Mask secrets and inline binary payloads in arbitrary log text."""
    redacted = _PRIVATE_KEY_RE.sub(MASKED_LOG_VALUE, str(text))
    redacted = _DATA_URL_RE.sub(
        lambda match: (
            f"data:{match.group('mime')};base64,"
            f"{OMITTED_BINARY_VALUE} ({len(match.group('data'))} chars)"
        ),
        redacted,
    )
    redacted = _redact_known_secret_values(redacted)
    redacted = _AUTH_HEADER_RE.sub(
        lambda match: f"{match.group('prefix')}{MASKED_LOG_VALUE}",
        redacted,
    )
    redacted = _COOKIE_HEADER_RE.sub(
        lambda match: f"{match.group('prefix')}{MASKED_LOG_VALUE}",
        redacted,
    )
    redacted = _BEARER_RE.sub(
        lambda match: f"{match.group('scheme')} {MASKED_LOG_VALUE}",
        redacted,
    )
    redacted = _QUOTED_ASSIGNMENT_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{MASKED_LOG_VALUE}{match.group('quote')}"
        ),
        redacted,
    )
    redacted = _UNQUOTED_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group('prefix')}{MASKED_LOG_VALUE}",
        redacted,
    )
    redacted = _URL_USERINFO_RE.sub(
        lambda match: (
            f"{match.group('scheme')}{match.group('user')}:{MASKED_LOG_VALUE}@"
        ),
        redacted,
    )
    for token_re in _HIGH_CONFIDENCE_TOKEN_RES:
        redacted = token_re.sub(MASKED_LOG_VALUE, redacted)
    return redacted


def _redact_log_value(
    value: Any,
    *,
    depth: int,
    seen: set[int],
) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_log_text(value)
    if isinstance(value, bytes):
        return f"{OMITTED_BINARY_VALUE} ({len(value)} bytes)"
    if depth >= 20:
        return "[nested value omitted]"

    value_id = id(value)
    if value_id in seen:
        return "[recursive value omitted]"
    seen.add(value_id)

    if isinstance(value, Mapping):
        normalized_path_hint = ""
        for hint_key in ("path", "field", "field_name", "setting", "setting_path"):
            hint_value = value.get(hint_key)
            if isinstance(hint_value, str):
                normalized_path_hint = hint_value
                if is_sensitive_log_field(hint_value):
                    break
        sibling_value_is_sensitive = bool(
            normalized_path_hint and is_sensitive_log_field(normalized_path_hint)
        )
        return {
            key: (
                MASKED_LOG_VALUE
                if (
                    is_sensitive_log_field(str(key))
                    or (
                        sibling_value_is_sensitive
                        and normalize_log_field_name(str(key))
                        in {
                            "current",
                            "current_value",
                            "new",
                            "new_value",
                            "old",
                            "old_value",
                            "value",
                        }
                    )
                )
                else _redact_log_value(item, depth=depth + 1, seen=seen)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _redact_log_value(item, depth=depth + 1, seen=seen)
            for item in value
        ]
    if hasattr(value, "model_dump"):
        try:
            return _redact_log_value(
                value.model_dump(mode="python"),
                depth=depth + 1,
                seen=seen,
            )
        except Exception:
            return redact_log_text(str(value))
    if is_dataclass(value) and not isinstance(value, type):
        return _redact_log_value(asdict(value), depth=depth + 1, seen=seen)
    if isinstance(value, BaseException):
        return redact_log_text(str(value))
    return redact_log_text(str(value))


def redact_log_value(value: Any) -> Any:
    """Recursively sanitize a value before it enters a log renderer."""
    return _redact_log_value(value, depth=0, seen=set())


def redact_structlog_event(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor that sanitizes the complete rendered event."""
    del logger, method_name
    sanitized = redact_log_value(event_dict)
    return sanitized if isinstance(sanitized, dict) else {"event": sanitized}


class RedactingFormatter(logging.Formatter):
    """Logging formatter that applies the final textual safety boundary."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


class RedactingTextStream:
    """Line-buffered stream wrapper for output written outside logging."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._buffer = ""
        self._lock = RLock()

    def write(self, value: str) -> int:
        text = str(value)
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._stream.write(f"{redact_log_text(line)}\n")
        return len(text)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        with self._lock:
            if self._buffer:
                self._stream.write(redact_log_text(self._buffer))
                self._buffer = ""
            self._stream.flush()

    def isatty(self) -> bool:
        return bool(self._stream.isatty())

    def fileno(self) -> int:
        return self._stream.fileno()

    @property
    def encoding(self) -> str | None:
        return self._stream.encoding

    @property
    def errors(self) -> str | None:
        return getattr(self._stream, "errors", None)

    @property
    def closed(self) -> bool:
        return self._stream.closed


def install_redacting_standard_streams() -> None:
    """Protect desktop sidecar stdout/stderr before they reach backend.log."""
    if not isinstance(sys.stdout, RedactingTextStream):
        sys.stdout = RedactingTextStream(sys.stdout)  # type: ignore[assignment]
    if not isinstance(sys.stderr, RedactingTextStream):
        sys.stderr = RedactingTextStream(sys.stderr)  # type: ignore[assignment]


__all__ = [
    "MASKED_LOG_VALUE",
    "OMITTED_BINARY_VALUE",
    "RedactingFormatter",
    "RedactingTextStream",
    "install_redacting_standard_streams",
    "is_sensitive_log_field",
    "normalize_log_field_name",
    "redact_log_text",
    "redact_log_value",
    "redact_structlog_event",
    "register_log_secret_values",
    "refresh_known_log_secrets",
]
