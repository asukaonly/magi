"""Write-only projection and update rules for MCP transport credentials."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..utils.log_redaction import is_sensitive_log_field

MASKED_MCP_SECRET = "***"
_HEADER_OPTIONS = frozenset({"h", "header"})
_ENV_OPTIONS = frozenset({"e", "env"})


class MaskedMCPSecretError(ValueError):
    """Raised when a masked credential cannot be safely restored."""


def mask_mcp_transport(transport: dict[str, Any]) -> dict[str, Any]:
    """Return an API-safe copy of one MCP transport."""
    masked = deepcopy(transport)
    if masked.get("kind") == "http":
        masked["url"] = _mask_url(str(masked.get("url") or ""))
        headers = masked.get("headers")
        if isinstance(headers, dict):
            masked["headers"] = {
                str(name): MASKED_MCP_SECRET if value else ""
                for name, value in headers.items()
            }
        return masked

    if masked.get("kind") == "stdio":
        args = masked.get("args")
        if isinstance(args, list):
            masked["args"] = _mask_args([str(arg) for arg in args])
        env = masked.get("env")
        if isinstance(env, dict):
            masked["env"] = {
                str(name): MASKED_MCP_SECRET if value else ""
                for name, value in env.items()
            }
    return masked


def restore_masked_mcp_transport(
    incoming: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    """Restore unchanged sentinels while preventing cross-target secret reuse."""
    restored = deepcopy(incoming)
    kind = restored.get("kind")
    if kind != existing.get("kind"):
        _reject_sentinels(restored)
        return restored
    if kind == "http":
        _restore_http_transport(restored, existing)
    elif kind == "stdio":
        _restore_stdio_transport(restored, existing)
    return restored


def reject_masked_mcp_transport(transport: dict[str, Any]) -> None:
    """Reject placeholders when there is no stored credential to preserve."""
    _reject_sentinels(transport)


def _restore_http_transport(incoming: dict[str, Any], existing: dict[str, Any]) -> None:
    incoming_url = str(incoming.get("url") or "")
    existing_url = str(existing.get("url") or "")
    if MASKED_MCP_SECRET in incoming_url:
        if incoming_url != _mask_url(existing_url):
            raise MaskedMCPSecretError(
                "MCP URL credentials must be re-entered after changing the server URL"
            )
        incoming["url"] = existing_url

    incoming_headers = incoming.get("headers")
    if not isinstance(incoming_headers, dict):
        return
    existing_headers = existing.get("headers")
    existing_headers = existing_headers if isinstance(existing_headers, dict) else {}
    if not any(value == MASKED_MCP_SECRET for value in incoming_headers.values()):
        return
    if not _same_url_origin(incoming_url, existing_url):
        raise MaskedMCPSecretError(
            "MCP HTTP credentials must be re-entered after changing the server origin"
        )
    for name, value in list(incoming_headers.items()):
        if value != MASKED_MCP_SECRET:
            continue
        if name not in existing_headers:
            raise MaskedMCPSecretError(f"MCP header {name!r} has no stored value to preserve")
        incoming_headers[name] = existing_headers[name]


def _restore_stdio_transport(incoming: dict[str, Any], existing: dict[str, Any]) -> None:
    incoming_args = [str(arg) for arg in incoming.get("args", []) or []]
    existing_args = [str(arg) for arg in existing.get("args", []) or []]
    incoming_env = incoming.get("env")
    incoming_env = incoming_env if isinstance(incoming_env, dict) else {}
    has_arg_sentinel = any(MASKED_MCP_SECRET in arg for arg in incoming_args)
    has_env_sentinel = any(value == MASKED_MCP_SECRET for value in incoming_env.values())
    if not has_arg_sentinel and not has_env_sentinel:
        return

    same_command = str(incoming.get("command") or "") == str(existing.get("command") or "")
    same_masked_args = incoming_args == _mask_args(existing_args)
    if not same_command or not same_masked_args:
        raise MaskedMCPSecretError(
            "MCP stdio credentials must be re-entered after changing the command or arguments"
        )
    if has_arg_sentinel:
        incoming["args"] = existing_args

    existing_env = existing.get("env")
    existing_env = existing_env if isinstance(existing_env, dict) else {}
    for name, value in list(incoming_env.items()):
        if value != MASKED_MCP_SECRET:
            continue
        if name not in existing_env:
            raise MaskedMCPSecretError(
                f"MCP environment variable {name!r} has no stored value to preserve"
            )
        incoming_env[name] = existing_env[name]


def _mask_args(args: list[str]) -> list[str]:
    masked = list(args)
    mask_next = False
    for index, argument in enumerate(args):
        if mask_next:
            masked[index] = _mask_assignment_or_header(argument, force=True)
            mask_next = False
            continue

        option, separator, inline_value = argument.partition("=")
        normalized_option = option.lstrip("-/")
        if normalized_option in _HEADER_OPTIONS or normalized_option in _ENV_OPTIONS:
            if separator:
                masked[index] = f"{option}={_mask_assignment_or_header(inline_value, force=True)}"
            else:
                mask_next = True
            continue
        if is_sensitive_log_field(normalized_option):
            if separator:
                masked[index] = f"{option}={MASKED_MCP_SECRET}"
            else:
                mask_next = True
            continue
        if separator and "://" in inline_value:
            masked[index] = f"{option}={_mask_url(inline_value)}"
            continue

        assignment = re.match(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$", argument)
        if assignment and is_sensitive_log_field(assignment.group("name")):
            masked[index] = f"{assignment.group('name')}={MASKED_MCP_SECRET}"
            continue
        masked[index] = _mask_url(argument) if "://" in argument else argument
    return masked


def _mask_assignment_or_header(value: str, *, force: bool) -> str:
    if "=" in value:
        name, assignment_value = value.split("=", 1)
        if force or is_sensitive_log_field(name):
            return f"{name}={MASKED_MCP_SECRET if assignment_value else ''}"
    if ":" in value:
        name, header_value = value.split(":", 1)
        if force or is_sensitive_log_field(name):
            return f"{name}:{MASKED_MCP_SECRET if header_value.strip() else ''}"
    return MASKED_MCP_SECRET if value and force else value


def _mask_url(raw_url: str) -> str:
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return raw_url
    if not parsed.scheme or not parsed.netloc:
        return raw_url

    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        if ":" in userinfo:
            username, password = userinfo.split(":", 1)
            userinfo = (
                f"{MASKED_MCP_SECRET if username else ''}:"
                f"{MASKED_MCP_SECRET if password else ''}"
            )
        elif userinfo:
            userinfo = MASKED_MCP_SECRET
        netloc = f"{userinfo}@{host}"

    query = urlencode(
        [
            (name, MASKED_MCP_SECRET if value and is_sensitive_log_field(name) else value)
            for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        ],
        doseq=True,
        safe="*",
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def _same_url_origin(left: str, right: str) -> bool:
    try:
        left_url = urlsplit(left)
        right_url = urlsplit(right)
        return (
            left_url.scheme.lower(),
            (left_url.hostname or "").lower(),
            left_url.port,
        ) == (
            right_url.scheme.lower(),
            (right_url.hostname or "").lower(),
            right_url.port,
        )
    except ValueError:
        return False


def _reject_sentinels(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _reject_sentinels(child)
        return
    if isinstance(value, list):
        for child in value:
            _reject_sentinels(child)
        return
    if isinstance(value, str) and MASKED_MCP_SECRET in value:
        raise MaskedMCPSecretError("Masked MCP credentials cannot be used without a stored value")


__all__ = [
    "MASKED_MCP_SECRET",
    "MaskedMCPSecretError",
    "mask_mcp_transport",
    "reject_masked_mcp_transport",
    "restore_masked_mcp_transport",
]
