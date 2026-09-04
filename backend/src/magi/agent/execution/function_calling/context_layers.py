"""Typed dynamic-context materialization for one unified agent run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi.utils.model_context_messages import (
    is_launch_context_message,
    is_runtime_owned_context_message,
    is_runtime_world_state_message,
    is_working_context_message,
    latest_runtime_world_state_content,
    runtime_message_provenance,
)


@dataclass(frozen=True, slots=True)
class DynamicContextEmission:
    """Records which typed layers were materialized for the next call."""

    runtime_state: bool = False
    working_context: bool = False
    launch_context: bool = False


def materialize_dynamic_context_layers(
    *,
    messages: list[dict[str, Any]],
    current_turn_id: str | None,
    current_turn_text: str,
    runtime_message: dict[str, Any] | None,
    working_message: dict[str, Any] | None,
    launch_message: dict[str, Any] | None,
) -> DynamicContextEmission:
    """Upsert typed dynamic context independently of user-message restoration."""

    if not messages:
        return DynamicContextEmission()
    if working_message is not None or launch_message is not None:
        messages[:] = [
            message
            for message in messages
            if not (working_message is not None and is_working_context_message(message))
            and not (launch_message is not None and is_launch_context_message(message))
        ]
    runtime_emitted = (
        runtime_message is not None
        and latest_runtime_world_state_content(messages)
        != str(runtime_message["content"]).strip()
    )
    if runtime_emitted:
        messages[:] = [
            message
            for message in messages
            if not is_runtime_world_state_message(message)
        ]
    current_user_index = _find_current_user_message_index(
        messages,
        current_turn_id=current_turn_id,
        current_turn_text=current_turn_text,
    )
    insert_at = current_user_index if current_user_index is not None else max(len(messages) - 1, 0)
    layers: list[dict[str, Any]] = []
    if runtime_emitted and runtime_message is not None:
        layers.append(runtime_message)
    if working_message is not None:
        layers.append(working_message)
    launch_emitted = launch_message is not None and not _has_completed_tool_iteration_after(
        messages,
        current_user_index,
    )
    if launch_emitted and launch_message is not None:
        layers.append(launch_message)
    messages[insert_at:insert_at] = layers
    return DynamicContextEmission(
        runtime_state=runtime_emitted,
        working_context=working_message is not None,
        launch_context=launch_emitted,
    )


def _find_current_user_message_index(
    messages: list[dict[str, Any]],
    *,
    current_turn_id: str | None,
    current_turn_text: str,
) -> int | None:
    normalized_turn_id = str(current_turn_id or "").strip()
    if normalized_turn_id:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not _is_user_authored_message(message):
                continue
            provenance = runtime_message_provenance(message)
            if provenance.get("origin_turn_id") == normalized_turn_id:
                return index
    normalized_text = str(current_turn_text or "").strip()
    if normalized_text:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if _is_user_authored_message(message) and _message_text(message) == normalized_text:
                return index
    for index in range(len(messages) - 1, -1, -1):
        if _is_user_authored_message(messages[index]):
            return index
    return None


def _is_user_authored_message(message: dict[str, Any]) -> bool:
    if str(message.get("role") or "").strip() != "user":
        return False
    if is_runtime_owned_context_message(message):
        return False
    text = _message_text(message)
    return not (
        text.startswith("[Runtime ")
        or text.startswith("[context compacted]")
        or text.startswith("[context truncated]")
    )


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text") or "").strip()
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and str(block.get("text") or "").strip()
    )


def _has_completed_tool_iteration_after(
    messages: list[dict[str, Any]],
    current_user_index: int | None,
) -> bool:
    if current_user_index is None:
        return False
    return any(
        str(message.get("role") or "").strip() in {"tool", "tool_result"}
        for message in messages[current_user_index + 1 :]
    )


__all__ = ["DynamicContextEmission", "materialize_dynamic_context_layers"]
