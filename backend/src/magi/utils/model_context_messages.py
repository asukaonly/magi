"""Typed provider-neutral messages used by model-context assembly."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.model_context_messages import (
    _RUNTIME_WORLD_STATE_TAG as _RUNTIME_WORLD_STATE_TAG,
    _WORKING_CONTEXT_TAG as _WORKING_CONTEXT_TAG,
    _LAUNCH_CONTEXT_TAG as _LAUNCH_CONTEXT_TAG,
    _RUNTIME_CONTEXT_KIND_KEY as _RUNTIME_CONTEXT_KIND_KEY,
    _RUNTIME_MESSAGE_PROVENANCE_KEY as _RUNTIME_MESSAGE_PROVENANCE_KEY,
    set_runtime_message_provenance,
    runtime_message_provenance,
    build_runtime_world_state_message,
    build_working_context_message,
    build_launch_context_message,
    is_runtime_world_state_message,
    is_working_context_message,
    is_launch_context_message,
    is_runtime_owned_context_message,
    strip_runtime_context_metadata,
    strip_runtime_message_provenance,
    latest_runtime_world_state_content,
    dynamic_context_start_index,
    current_dynamic_context_messages,
    _is_typed_context_message as _is_typed_context_message,
    _message_text as _message_text,
)

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
    "runtime_message_provenance",
    "set_runtime_message_provenance",
    "strip_runtime_context_metadata",
    "strip_runtime_message_provenance",
]
