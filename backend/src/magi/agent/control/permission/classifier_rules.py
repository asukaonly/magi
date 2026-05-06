"""Per-tool risk classification rules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .classifier_models import ClassificationResult, RiskSignal
from .contracts import RiskLevel


def _classify_shell(arguments: dict[str, Any]) -> ClassificationResult:
    """Lazy bridge to the shared bash command classifier.

    Imported lazily because :mod:`magi.tools.builtin._bash_grading` lives in
    the tools tree and would create a cross-package import cycle if pulled at
    module-load time.
    """
    from ....tools.builtin._bash_grading import classify_for_permission
    return classify_for_permission(arguments)


def _classify_file_write(arguments: dict[str, Any]) -> ClassificationResult:
    path = arguments.get("path") or arguments.get("file_path") or ""
    signals = [RiskSignal(key="fs_write", description="filesystem write")]
    if isinstance(path, str) and _is_sensitive_user_path(path):
        signals.append(
            RiskSignal(key="sensitive_user_path", description="writes to user-sensitive path")
        )
        return ClassificationResult(
            level=RiskLevel.DESTRUCTIVE, signals=signals, preview=path[:200]
        )
    return ClassificationResult(
        level=RiskLevel.MEDIUM,
        signals=signals,
        preview=str(path)[:200] if path else None,
    )


def _classify_file_edit(arguments: dict[str, Any]) -> ClassificationResult:
    path = arguments.get("path") or arguments.get("file_path") or ""
    signals = [RiskSignal(key="fs_edit", description="filesystem edit")]
    if isinstance(path, str) and _is_sensitive_user_path(path):
        signals.append(
            RiskSignal(key="sensitive_user_path", description="edits user-sensitive path")
        )
        return ClassificationResult(
            level=RiskLevel.DESTRUCTIVE, signals=signals, preview=path[:200]
        )
    return ClassificationResult(
        level=RiskLevel.MEDIUM,
        signals=signals,
        preview=str(path)[:200] if path else None,
    )


def _classify_web_fetch(arguments: dict[str, Any]) -> ClassificationResult:
    url = arguments.get("url") or arguments.get("uri") or ""
    return ClassificationResult(
        level=RiskLevel.MEDIUM,
        signals=[RiskSignal(key="network_fetch", description="outbound network request")],
        preview=str(url)[:200] if url else None,
    )


def _classify_web_search(arguments: dict[str, Any]) -> ClassificationResult:
    query = arguments.get("query") or ""
    return ClassificationResult(
        level=RiskLevel.LOW,
        signals=[RiskSignal(key="network_search", description="web search")],
        preview=str(query)[:200] if query else None,
    )


def _classify_send_message(arguments: dict[str, Any]) -> ClassificationResult:
    signals = [
        RiskSignal(key="external_side_effect", description="sends a message externally")
    ]
    channel = arguments.get("channel") or arguments.get("target") or ""
    return ClassificationResult(
        level=RiskLevel.HIGH,
        signals=signals,
        preview=str(channel)[:200] if channel else None,
    )


def _classify_image_generation(arguments: dict[str, Any]) -> ClassificationResult:
    prompt = arguments.get("prompt") or ""
    return ClassificationResult(
        level=RiskLevel.HIGH,
        signals=[
            RiskSignal(
                key="provider_generation",
                description="external image generation request",
            ),
            RiskSignal(key="fs_write", description="writes generated image artifacts"),
        ],
        preview=str(prompt)[:200] if prompt else None,
    )


def _classify_file_read(arguments: dict[str, Any]) -> ClassificationResult:
    path = arguments.get("path") or arguments.get("file_path") or ""
    return ClassificationResult(
        level=RiskLevel.LOW,
        signals=[RiskSignal(key="fs_read", description="filesystem read")],
        preview=str(path)[:200] if path else None,
    )


_SENSITIVE_USER_PATH_SUFFIXES: tuple[str, ...] = (
    "/.ssh/",
    "/.aws/credentials",
    "/.gnupg/",
    "/.config/gh/hosts.yml",
    "/.netrc",
)


def _is_sensitive_user_path(path: str) -> bool:
    probe = path.replace("\\", "/")
    return any(marker in probe for marker in _SENSITIVE_USER_PATH_SUFFIXES)


RULES: dict[str, Callable[[dict[str, Any]], ClassificationResult]] = {
    "bash": _classify_shell,
    "shell": _classify_shell,
    "execute_command": _classify_shell,
    "run_command": _classify_shell,
    "file_write": _classify_file_write,
    "write_file": _classify_file_write,
    "file_edit": _classify_file_edit,
    "edit_file": _classify_file_edit,
    "apply_patch": _classify_file_edit,
    "str_replace_editor": _classify_file_edit,
    "file_read": _classify_file_read,
    "read_file": _classify_file_read,
    "web_fetch": _classify_web_fetch,
    "fetch_url": _classify_web_fetch,
    "http_request": _classify_web_fetch,
    "web_search": _classify_web_search,
    "search_web": _classify_web_search,
    "send_message": _classify_send_message,
    "send_email": _classify_send_message,
    "telegram_send": _classify_send_message,
    "email_send": _classify_send_message,
    "post_message": _classify_send_message,
    "publish_message": _classify_send_message,
    "notify_user": _classify_send_message,
    "notification_send": _classify_send_message,
    "sms_send": _classify_send_message,
    "image-generation": _classify_image_generation,
    "image_generation": _classify_image_generation,
}

EXTERNAL_SEND_SUBSTRINGS: tuple[str, ...] = (
    "send_message",
    "send_email",
    "send_sms",
    "send_notification",
    "post_message",
    "publish_message",
    "notify_user",
)


def classify_external_send(arguments: dict[str, Any]) -> ClassificationResult:
    return _classify_send_message(arguments)


__all__ = ["EXTERNAL_SEND_SUBSTRINGS", "RULES", "classify_external_send"]
