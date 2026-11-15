"""Provider-neutral model-context records owned by the chat domain."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.chat_model_context import (
    ModelContextItemKind,
    ModelContextScope,
    ModelContextItem,
    ModelContextEvent,
    ModelContextSnapshot,
    ModelContextEpoch,
    ModelContextBoundary,
    ModelContextCallSnapshot,
    ModelContextRevisionConflictError,
    ModelContextRunClosedError,
    infer_model_context_item_kind,
)

__all__ = [
    "ModelContextBoundary",
    "ModelContextCallSnapshot",
    "ModelContextEpoch",
    "ModelContextEvent",
    "ModelContextItem",
    "ModelContextItemKind",
    "ModelContextRevisionConflictError",
    "ModelContextRunClosedError",
    "ModelContextScope",
    "ModelContextSnapshot",
    "infer_model_context_item_kind",
]
