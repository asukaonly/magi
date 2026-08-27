"""Typed provider-neutral messages used by model-context assembly."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


_RUNTIME_WORLD_STATE_TAG = "runtime_world_state"
_WORKING_CONTEXT_TAG = "working_context"
_LAUNCH_CONTEXT_TAG = "launch_context"
_RUNTIME_CONTEXT_KIND_KEY = "_magi_context_kind"


def build_runtime_world_state_message(content: str) -> dict[str, Any] | None:
    """Build a durable runtime-owned world-state snapshot message."""

    normalized = str(content or "").strip()
    if not normalized:
        return None
    return {
        "role": "user",
        _RUNTIME_CONTEXT_KIND_KEY: _RUNTIME_WORLD_STATE_TAG,
        "content": (
            f"<{_RUNTIME_WORLD_STATE_TAG}>\n"
            "[Runtime-provided state; not authored by the user. This snapshot "
            "supersedes earlier runtime-world-state values.]\n"
            f"{normalized}\n"
            f"</{_RUNTIME_WORLD_STATE_TAG}>"
        ),
    }


def build_working_context_message(content: str) -> dict[str, Any] | None:
    """Build run-local context that must not enter the accepted surface."""

    normalized = str(content or "").strip()
    if not normalized:
        return None
    return {
        "role": "user",
        _RUNTIME_CONTEXT_KIND_KEY: _WORKING_CONTEXT_TAG,
        "content": (
            f"<{_WORKING_CONTEXT_TAG}>\n"
            "[Runtime-provided context for this run; not authored by the user "
            "and not a durable conversation turn.]\n"
            f"{normalized}\n"
            f"</{_WORKING_CONTEXT_TAG}>"
        ),
    }


def build_launch_context_message(content: str) -> dict[str, Any] | None:
    """Build launch-only context that expires after the first tool iteration."""

    normalized = str(content or "").strip()
    if not normalized:
        return None
    return {
        "role": "user",
        _RUNTIME_CONTEXT_KIND_KEY: _LAUNCH_CONTEXT_TAG,
        "content": (
            f"<{_LAUNCH_CONTEXT_TAG}>\n"
            "[Runtime-provided launch snapshot; not authored by the user. Use "
            "it only to understand why this run started. Later decisions must "
            "rely on the assigned task and observed tool results.]\n"
            f"{normalized}\n"
            f"</{_LAUNCH_CONTEXT_TAG}>"
        ),
    }


def is_runtime_world_state_message(message: Mapping[str, Any]) -> bool:
    """Return whether a message carries a runtime world-state snapshot."""

    return _is_typed_context_message(message, _RUNTIME_WORLD_STATE_TAG)


def is_working_context_message(message: Mapping[str, Any]) -> bool:
    """Return whether a message carries run-local working context."""

    return _is_typed_context_message(message, _WORKING_CONTEXT_TAG)


def is_launch_context_message(message: Mapping[str, Any]) -> bool:
    """Return whether a message carries launch-only runtime context."""

    return _is_typed_context_message(message, _LAUNCH_CONTEXT_TAG)


def is_runtime_owned_context_message(message: Mapping[str, Any]) -> bool:
    """Return whether a message belongs to any typed runtime context layer."""

    return (
        is_runtime_world_state_message(message)
        or is_working_context_message(message)
        or is_launch_context_message(message)
    )


def strip_runtime_context_metadata(message: Mapping[str, Any]) -> dict[str, Any]:
    """Return a provider-safe message without runtime-only type metadata."""

    return {
        key: value
        for key, value in message.items()
        if key != _RUNTIME_CONTEXT_KIND_KEY
    }


def latest_runtime_world_state_content(
    messages: Sequence[Mapping[str, Any]],
) -> str | None:
    """Return the latest runtime-state message content for change detection."""

    for message in reversed(messages):
        if is_runtime_world_state_message(message):
            return _message_text(message).strip()
    return None


def dynamic_context_start_index(messages: Sequence[Mapping[str, Any]]) -> int:
    """Return the first volatile context index for the current model call."""

    for end_index in range(len(messages) - 1, -1, -1):
        if not is_runtime_owned_context_message(messages[end_index]):
            continue
        start_index = end_index
        while start_index > 0 and is_runtime_owned_context_message(
            messages[start_index - 1]
        ):
            start_index -= 1
        return start_index
    return -1


def current_dynamic_context_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return only the typed dynamic messages preceding the current user turn."""

    start_index = dynamic_context_start_index(messages)
    if start_index < 0:
        return []
    dynamic: list[Mapping[str, Any]] = []
    for message in messages[start_index:]:
        if not is_runtime_owned_context_message(message):
            break
        dynamic.append(message)
    return dynamic


def _is_typed_context_message(message: Mapping[str, Any], tag: str) -> bool:
    if str(message.get(_RUNTIME_CONTEXT_KIND_KEY) or "") != tag:
        return False
    if str(message.get("role") or "").strip() != "user":
        return False
    return _message_text(message).lstrip().startswith(f"<{tag}>")


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            continue
        parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


__all__ = [
    "build_launch_context_message",
    "build_runtime_world_state_message",
    "build_working_context_message",
    "current_dynamic_context_messages",
    "dynamic_context_start_index",
    "is_launch_context_message",
    "is_runtime_owned_context_message",
    "is_runtime_world_state_message",
    "is_working_context_message",
    "latest_runtime_world_state_content",
    "strip_runtime_context_metadata",
]
