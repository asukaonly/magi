"""Credential registration and redaction for MCP-owned diagnostic output."""

from __future__ import annotations

import base64
import re
from threading import RLock
from typing import Any, Mapping
import traceback
from urllib.parse import parse_qsl, quote, quote_plus, unquote, urlsplit

from ..utils.log_redaction import (
    is_sensitive_log_field,
    redact_log_text,
    register_log_secret_values,
)

_MCP_SECRET_LOCK = RLock()
_MCP_SECRET_VALUES: tuple[str, ...] = ()


def _secret_fragments(value: str) -> set[str]:
    fragments = {value}
    scheme, separator, credential = value.partition(" ")
    if separator and scheme.lower() in {"bearer", "basic"} and credential:
        fragments.add(credential)
        if scheme.lower() == "basic":
            try:
                decoded = base64.b64decode(credential, validate=True).decode(
                    "utf-8",
                    errors="ignore",
                )
            except (ValueError, UnicodeDecodeError):
                decoded = ""
            if decoded:
                fragments.add(decoded)
                _username, colon, password = decoded.partition(":")
                if colon and password:
                    fragments.add(password)

    if ";" in value and "=" in value:
        for item in value.split(";"):
            _name, equals, item_value = item.strip().partition("=")
            if equals and item_value:
                fragments.add(item_value)
    return {fragment for fragment in fragments if fragment}


def _url_secrets(value: Any) -> set[str]:
    raw_url = str(value or "")
    if not raw_url:
        return set()
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return set()

    secrets: set[str] = set()
    if parsed.username:
        secrets.add(unquote(parsed.username))
    if parsed.password:
        secrets.add(unquote(parsed.password))
    for key, item in parse_qsl(parsed.query, keep_blank_values=False):
        if item and is_sensitive_log_field(key):
            secrets.add(item)
    return secrets


def _register_secret_sets(
    *,
    local_secrets: set[str],
    global_secrets: set[str],
) -> None:
    variants: set[str] = set()
    for secret in local_secrets:
        for fragment in _secret_fragments(secret):
            variants.update(
                {
                    fragment,
                    quote(fragment, safe=""),
                    quote_plus(fragment, safe=""),
                }
            )

    global _MCP_SECRET_VALUES
    with _MCP_SECRET_LOCK:
        variants.update(_MCP_SECRET_VALUES)
        _MCP_SECRET_VALUES = tuple(
            sorted(filter(None, variants), key=len, reverse=True)
        )

    expanded_global: set[str] = set()
    for secret in global_secrets:
        expanded_global.update(_secret_fragments(secret))
    register_log_secret_values(expanded_global)


def register_mcp_runtime_secrets(values: list[str]) -> None:
    """Register credentials learned during a live MCP connection."""
    secrets = {str(value) for value in values if str(value or "")}
    _register_secret_sets(local_secrets=secrets, global_secrets=secrets)


def register_mcp_transport_secrets(value: Any) -> None:
    """Register values from MCP fields that are intended to carry credentials."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if not isinstance(value, Mapping):
        return

    transport = value.get("transport", value)
    if hasattr(transport, "model_dump"):
        transport = transport.model_dump(mode="python")
    if not isinstance(transport, Mapping):
        return

    local_secrets: set[str] = set()
    global_secrets: set[str] = set()
    url_secrets = _url_secrets(transport.get("url"))
    local_secrets.update(url_secrets)
    global_secrets.update(url_secrets)

    for container_name in ("env", "headers"):
        container = transport.get(container_name)
        if not isinstance(container, Mapping):
            continue
        for key, item in container.items():
            if not item:
                continue
            secret = str(item)
            field_is_sensitive = is_sensitive_log_field(str(key))
            if field_is_sensitive or len(secret) >= 6:
                local_secrets.add(secret)
            if field_is_sensitive or len(secret) >= 6:
                global_secrets.add(secret)

    args = transport.get("args")
    if isinstance(args, list):
        for index, raw_arg in enumerate(args):
            argument = str(raw_arg or "")
            option, separator, inline_value = argument.partition("=")
            normalized_option = option.lstrip("-/")
            next_value = (
                str(args[index + 1])
                if not separator and index + 1 < len(args)
                else ""
            )
            candidate = inline_value if separator else next_value
            if not candidate:
                continue

            if normalized_option in {"H", "header"}:
                header_name, colon, header_value = candidate.partition(":")
                if colon and header_value.strip():
                    secret = header_value.strip()
                    local_secrets.add(secret)
                    if is_sensitive_log_field(header_name) or len(secret) >= 6:
                        global_secrets.add(secret)
                continue

            if normalized_option in {"e", "env"}:
                env_name, equals, env_value = candidate.partition("=")
                if equals and env_value:
                    local_secrets.add(env_value)
                    if is_sensitive_log_field(env_name) or len(env_value) >= 6:
                        global_secrets.add(env_value)
                continue

            if is_sensitive_log_field(normalized_option):
                local_secrets.add(candidate)
                global_secrets.add(candidate)

    _register_secret_sets(
        local_secrets=local_secrets,
        global_secrets=global_secrets,
    )


def redact_mcp_log_text(value: Any) -> str | None:
    """Redact an MCP error or stderr line before caching or returning it."""
    if value is None:
        return None
    redacted = str(value)
    with _MCP_SECRET_LOCK:
        secrets = _MCP_SECRET_VALUES
    for secret in secrets:
        if len(secret) >= 6:
            redacted = redacted.replace(secret, "[REDACTED]")
            continue
        redacted = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(secret)}(?![A-Za-z0-9])",
            "[REDACTED]",
            redacted,
        )
    return redact_log_text(redacted)


def redact_mcp_traceback(exc: BaseException) -> str:
    """Preserve an MCP traceback while removing locally registered secrets."""
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return redact_mcp_log_text(rendered) or type(exc).__name__


__all__ = [
    "redact_mcp_log_text",
    "redact_mcp_traceback",
    "register_mcp_runtime_secrets",
    "register_mcp_transport_secrets",
]
